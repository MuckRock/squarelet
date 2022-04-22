# Django
from django.contrib.postgres.fields import CIEmailField
from django.db import models, transaction
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import uuid

# Third Party
import stripe
from autoslug import AutoSlugField
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.mixins import AvatarMixin
from squarelet.core.utils import file_path
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.choices import ChangeLogReason, StripeAccounts
from squarelet.organizations.models.payment import Charge
from squarelet.organizations.querysets import (
    InvitationQuerySet,
    MembershipQuerySet,
    OrganizationQuerySet,
)

stripe.api_version = "2018-09-24"


def organization_file_path(instance, filename):
    return file_path("org_avatars", instance, filename)


class Organization(AvatarMixin, models.Model):
    """Orginization to allow pooled requests and collaboration"""

    objects = OrganizationQuerySet.as_manager()

    uuid = models.UUIDField(
        _("UUID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("Uniquely identify the organization across services"),
    )

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The name of the organization")
    )
    slug = AutoSlugField(
        _("slug"),
        populate_from="name",
        unique=True,
        help_text=_("A unique slug for use in URLs"),
    )
    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this organization was created")
    )
    updated_at = AutoLastModifiedField(
        _("updated at"), help_text=_("When this organization was last updated")
    )

    avatar = ImageField(
        _("avatar"),
        upload_to=organization_file_path,
        blank=True,
        help_text=_("An image to represent the organization"),
    )

    users = models.ManyToManyField(
        verbose_name=_("users"),
        to="users.User",
        through="organizations.Membership",
        related_name="organizations",
        help_text=_("The user's in this organization"),
    )

    subtypes = models.ManyToManyField(
        verbose_name=_("subtypes"),
        to="organizations.OrganizationSubtype",
        related_name="organizations",
        help_text=_("The subtypes of this organization"),
        blank=True,
    )

    # remove these
    _plan = models.ForeignKey(
        verbose_name=_("plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        help_text=_("The current plan this organization is subscribed to"),
        blank=True,
        null=True,
        db_column="plan_id",
    )
    next_plan = models.ForeignKey(
        verbose_name=_("next plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="pending_organizations",
        help_text=_(
            "The pending plan to be updated to on the next billing cycle - "
            "used when downgrading a plan to let the organization finish out a "
            "subscription is paid for"
        ),
        blank=True,
        null=True,
    )
    # end remove these

    plans = models.ManyToManyField(
        verbose_name=_("plans"),
        to="organizations.Plan",
        through="organizations.Subscription",
        related_name="organizations",
        help_text=_("Plans this organization is subscribed to"),
        blank=True,
    )

    individual = models.BooleanField(
        _("individual organization"),
        default=False,
        help_text=_("This organization is solely for the use of one user"),
    )
    private = models.BooleanField(
        _("private organization"),
        default=False,
        help_text=_(
            "This organization's information and membership is not made public"
        ),
    )
    verified_journalist = models.BooleanField(
        _("verified journalist"),
        default=False,
        help_text=_("This organization is a verified jorunalistic organization"),
    )

    # Book keeping
    max_users = models.IntegerField(
        _("maximum users"),
        default=5,
        help_text=_("The maximum number of users in this organization"),
    )
    # this moved to subscription, remove
    update_on = models.DateField(
        _("date update"),
        null=True,
        blank=True,
        help_text=_("Date when monthly requests are restored"),
    )

    # stripe
    # moved to customer, remove
    customer_id = models.CharField(
        _("customer id"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("The organization's corresponding ID on stripe"),
    )
    # move to subscription, remove
    subscription_id = models.CharField(
        _("subscription id"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("The organization's corresponding subscription ID on stripe"),
    )
    # should this be moved to customer?
    payment_failed = models.BooleanField(
        _("payment failed"),
        default=False,
        help_text=_(
            "A payment for this organization has failed - they should update their "
            "payment information"
        ),
    )

    default_avatar = static("images/avatars/organization.png")

    class Meta:
        ordering = ("slug",)

    def __str__(self):
        if self.individual:
            return f"{self.name} (Individual)"
        else:
            return self.name

    def save(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("organization", self.uuid)
            )

    def get_absolute_url(self):
        """The url for this object"""
        if self.individual:
            # individual orgs do not have a detail page, use the user's page
            return self.user.get_absolute_url()
        else:
            return reverse("organizations:detail", kwargs={"slug": self.slug})

    @property
    def email(self):
        """Get an email for this organization"""
        if self.individual:
            return self.user.email

        receipt_email = self.receipt_emails.first()
        if receipt_email:
            return receipt_email.email

        user = self.users.filter(memberships__admin=True).first()
        if user:
            return user.email

        return None

    @property
    def name(self):
        """Get a name for this organization"""
        if self.individual:
            return self.user.name

        user = self.users.filter(memberships__admin=True).first()
        if user:
            return user.name

        return ""

    # User Management
    def has_admin(self, user):
        """Is the given user an admin of this organization"""
        return self.users.filter(pk=user.pk, memberships__admin=True).exists()

    def has_member(self, user):
        """Is the user a member?"""
        return self.users.filter(pk=user.pk).exists()

    def user_count(self):
        """Count the number of users, including pending invitations"""
        return self.users.count() + self.invitations.get_pending().count()

    def add_creator(self, user):
        """Add user as the creator of the organization"""
        # add creator to the organization as an admin by default
        self.memberships.create(user=user, admin=True)
        # add the creators email as a receipt recipient by default
        # agency users may not have an email
        if user.email:
            self.receipt_emails.create(email=user.email)

    @mproperty
    def reference_name(self):
        if self.individual:
            return _("Your account")
        return self.name

    # Payment Management

    def customer(self, stripe_account):
        """Retrieve the customer from Stripe or create one if it doesn't exist"""
        customer, _ = self.customers.get_or_create(stripe_account=stripe_account)
        return customer

    def save_card(self, token, stripe_account):
        self.payment_failed = False
        self.save()
        self.customer(stripe_account).save_card(token)
        send_cache_invalidations("organization", self.uuid)

    def remove_card(self, stripe_account):
        self.customer(stripe_account).remove_card()
        send_cache_invalidations("organization", self.uuid)

    @mproperty
    def plan(self):
        return self.plans.muckrock().first()

    @mproperty
    def subscription(self):
        return self.subscriptions.muckrock().first()

    def create_subscription(self, token, plan):
        if token:
            self.save_card(token, plan.stripe_account)

        customer = self.customer(plan.stripe_account).stripe_customer
        if not customer.email:
            customer.email = self.email
            customer.save()

        self.subscriptions.start(organization=self, plan=plan)

    def set_subscription(self, token, plan, max_users, user):
        if self.individual:
            max_users = 1
        if token and plan:
            self.save_card(token, plan.stripe_account)

        # store so we can log
        from_plan, from_max_users = (self.plan, self.max_users)

        self.max_users = max_users
        self.save()

        if not self.plan and plan:
            # create a subscription going from no plan to plan
            self.create_subscription(token, plan)
        elif self.plan and not plan:
            # cancel a subscription going from plan to no plan
            self.subscription.cancel()
        elif self.plan and plan:
            # modify the subscription
            self.subscription.modify(plan)

        self.change_logs.create(
            user=user,
            reason=ChangeLogReason.updated,
            from_plan=from_plan,
            from_max_users=from_max_users,
            to_plan=plan,
            to_max_users=self.max_users,
        )

    def subscription_cancelled(self):
        """The subsctription was cancelled due to payment failure"""
        self.change_logs.create(
            reason=ChangeLogReason.failed,
            from_plan=self.plan,
            from_max_users=self.max_users,
            to_max_users=self.max_users,
        )
        self.subscription.delete()

    def charge(
        self,
        amount,
        description,
        fee_amount=0,
        token=None,
        save_card=False,
        metadata=None,
        stripe_account=StripeAccounts.muckrock,
    ):
        """Charge the organization and optionally save their credit card"""
        if save_card:
            self.save_card(token, stripe_account)
            token = None
        if metadata is None:
            metadata = {}
        charge = Charge.objects.make_charge(
            self, token, amount, fee_amount, description, stripe_account, metadata
        )
        return charge

    def set_receipt_emails(self, emails):
        new_emails = set(emails)
        old_emails = {r.email for r in self.receipt_emails.all()}
        self.receipt_emails.filter(email__in=old_emails - new_emails).delete()
        ReceiptEmail.objects.bulk_create(
            [ReceiptEmail(organization=self, email=e) for e in new_emails - old_emails]
        )


class Membership(models.Model):
    """Through table for organization membership"""

    objects = MembershipQuerySet.as_manager()

    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    admin = models.BooleanField(
        _("admin"),
        default=False,
        help_text=_("This user has administrative rights for this organization"),
    )

    class Meta:
        unique_together = ("user", "organization")
        ordering = ("user_id",)

    def __str__(self):
        return f"Membership: {self.user} in {self.organization}"

    def save(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user.uuid)
            )

    def delete(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user.uuid)
            )


class Invitation(models.Model):
    """An invitation for a user to join an organization"""

    objects = InvitationQuerySet.as_manager()

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        related_name="invitations",
        on_delete=models.CASCADE,
        help_text=_("The organization this invitation is for"),
    )
    uuid = models.UUIDField(
        _("UUID"),
        default=uuid.uuid4,
        editable=False,
        help_text=_("This UUID serves as a secret token for this invitation in URLs"),
    )
    email = models.EmailField(
        _("email"), help_text=_("The email address to send this invitation to")
    )
    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="invitations",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_(
            "The user this invitation is for.  Used if a user requested an "
            "invitation directly as opposed to an admin inviting them via email."
        ),
    )
    request = models.BooleanField(
        _("request"),
        help_text="Is this a request for an invitation from the user or an invitation "
        "to the user from an admin?",
        default=False,
    )
    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this invitation was created")
    )
    accepted_at = models.DateTimeField(
        _("accepted at"),
        blank=True,
        null=True,
        help_text=_(
            "When this invitation was accepted.  NULL signifies it has not been "
            "accepted yet"
        ),
    )
    rejected_at = models.DateTimeField(
        _("rejected at"),
        blank=True,
        null=True,
        help_text=_(
            "When this invitation was rejected.  NULL signifies it has not been "
            "rejected yet"
        ),
    )

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Invitation: {self.uuid}"

    def send(self, source=None):

        # default source to "muckrock" in case this is called without a value
        if source is None:
            source = "muckrock"

        if self.request:
            send_mail(
                subject=_(f"{self.user} has requested to join {self.organization}"),
                template="organizations/email/join_request.html",
                organization=self.organization,
                organization_to=ORG_TO_ADMINS,
                source=source,
                extra_context={"joiner": self.user},
            )
        else:
            send_mail(
                subject=_(f"Invitation to join {self.organization.name}"),
                template="organizations/email/invitation.html",
                to=[self.email],
                source=source,
                extra_context={"invitation": self},
            )

    @transaction.atomic
    def accept(self, user=None):
        """Accept the invitation"""
        if self.user is None and user is None:
            raise ValueError(
                "Must give a user when accepting if invitation has no user"
            )
        if self.accepted_at or self.rejected_at:
            raise ValueError("This invitation has already been closed")
        if self.user is None:
            self.user = user
        self.accepted_at = timezone.now()
        self.save()
        if not self.organization.has_member(self.user):
            Membership.objects.create(organization=self.organization, user=self.user)

    def reject(self):
        """Reject or revoke the invitation"""
        if self.accepted_at or self.rejected_at:
            raise ValueError("This invitation has already been closed")
        self.rejected_at = timezone.now()
        self.save()

    def get_name(self):
        """Returns the name or email if no name is set"""
        if self.user is not None and self.user.name:
            return self.user.name
        else:
            return self.email


class ReceiptEmail(models.Model):
    """An email address to send receipts to"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        related_name="receipt_emails",
        on_delete=models.CASCADE,
        help_text=_("The organization this receipt email corresponds to"),
    )
    email = CIEmailField(
        _("email"), help_text=_("The email address to send the receipt to")
    )
    failed = models.BooleanField(
        _("failed"),
        default=False,
        help_text=_("Has sending to this email address failed?"),
    )

    class Meta:
        unique_together = ("organization", "email")

    def __str__(self):
        return f"Receipt Email: <{self.email}>"


class OrganizationChangeLog(models.Model):
    """Track important changes to organizations"""

    created_at = AutoCreatedField(
        _("created at"), help_text=_("When the organization was changed")
    )

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="change_logs",
        help_text=_("The organization which changed"),
    )
    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="change_logs",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_("The user who changed the organization"),
    )
    reason = models.PositiveSmallIntegerField(
        _("reason"),
        choices=ChangeLogReason.choices,
        help_text=_("Which category of change occurred"),
    )

    from_plan = models.ForeignKey(
        verbose_name=_("from plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan before the change occurred"),
    )
    from_next_plan = models.ForeignKey(
        verbose_name=_("from next plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's next_plan before the change occurred"),
    )
    from_max_users = models.IntegerField(
        _("maximum users"),
        blank=True,
        null=True,
        help_text=_("The organization's max_users before the change occurred"),
    )

    to_plan = models.ForeignKey(
        verbose_name=_("to plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan after the change occurred"),
    )
    to_next_plan = models.ForeignKey(
        verbose_name=_("to next plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan after the change occurred"),
    )
    to_max_users = models.IntegerField(
        _("maximum users"),
        help_text=_("The organization's max_users after the change occurred"),
    )


class OrganizationType(models.Model):
    """A broad type an organization may be classified as"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The name of the organization type")
    )

    def __str__(self):
        return self.name


class OrganizationSubtype(models.Model):
    """A specific type an organization may be classified as"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The name of the organization subtype")
    )
    type = models.ForeignKey(
        verbose_name=_("type"),
        to="organizations.OrganizationType",
        on_delete=models.PROTECT,
        related_name="subtypes",
        help_text=_("The parent type for this subtype"),
    )

    def __str__(self):
        return self.name
