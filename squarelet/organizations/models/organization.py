# pylint: disable=too-many-lines
# Django
from django.db import models, transaction
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys
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
from squarelet.core.utils import file_path, mailchimp_journey
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.choices import (
    COUNTRY_CHOICES,
    STATE_CHOICES,
    ChangeLogReason,
)
from squarelet.organizations.models.payment import Charge
from squarelet.organizations.querysets import (
    InvitationQuerySet,
    MembershipQuerySet,
    OrganizationQuerySet,
)

logger = logging.getLogger(__name__)


def organization_file_path(instance, filename):
    return file_path("org_avatars", instance, filename)


class Organization(AvatarMixin, models.Model):
    """Organizations allow collaboration and resource sharing"""

    # pylint: disable=too-many-public-methods

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

    members = models.ManyToManyField(
        verbose_name=_("members"),
        to="self",
        related_name="groups",
        help_text=_(
            "Organizations which are members of this organization "
            "(useful for trade associations or other member groups)"
        ),
        limit_choices_to={"individual": False},
        blank=True,
        symmetrical=False,
    )
    parent = models.ForeignKey(
        verbose_name=_("parent"),
        to="self",
        on_delete=models.PROTECT,
        related_name="children",
        help_text=_("The parent organization"),
        limit_choices_to={"individual": False},
        blank=True,
        null=True,
    )
    wikidata_id = models.CharField(
        _("wikidata id"),
        max_length=255,
        blank=True,
        help_text=_("The wikidata identifier"),
    )

    city = models.CharField(
        _("city"),
        max_length=100,
        blank=True,
    )
    state = models.CharField(
        _("state"),
        max_length=2,
        blank=True,
        choices=STATE_CHOICES,
    )
    country = models.CharField(
        _("country"),
        max_length=2,
        blank=True,
        choices=COUNTRY_CHOICES,
    )

    # originally for the Election Resources hub, now keeping for posterity
    hub_eligible = models.BooleanField(
        _("hub eligible"),
        blank=True,
        default=False,
        help_text=_(
            "This org and its members and children may access the resource hub"
        ),
    )

    # TODO: remove these
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

    # Every user has an individual organization
    # created when creating an account. Its UUID
    # is used to identify the user across services.
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
        help_text=_("This organization is a verified journalistic organization"),
    )

    # Book keeping
    max_users = models.IntegerField(
        _("resource blocks"),
        default=5,
        help_text=_("The number of resource blocks this organization receives monthly"),
    )
    # TODO: this moved to subscription, remove
    update_on = models.DateField(
        _("date update"),
        null=True,
        blank=True,
        help_text=_("Date when monthly requests are restored"),
    )

    # TODO: remove stripe properties that moved to other models
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

    merged = models.ForeignKey(
        verbose_name=_("merged into"),
        to="self",
        on_delete=models.PROTECT,
        related_name="+",
        help_text=_("The organization this organization was merged in to"),
        blank=True,
        null=True,
    )
    merged_at = models.DateTimeField(
        _("merged at"),
        blank=True,
        null=True,
        help_text=_("When this organization was merged"),
    )
    merged_by = models.ForeignKey(
        verbose_name=_("merged by"),
        to="users.User",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
    )

    # TODO: Remove default avatar
    default_avatar = static("images/avatars/organization.png")

    allow_auto_join = models.BooleanField(
        default=False,
        help_text=(
            "Allow users to join automatically if one "
            "of their verified emails matches the email domain for this organization."
        ),
    )

    class Meta:
        ordering = ("slug",)
        permissions = (("merge_organization", "Can merge organizations"),)

    def __str__(self):
        if self.individual:
            return f"{self.name} (Individual)"
        else:
            return self.name

    def save(self, *args, **kwargs):
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

        # If a group organization, first try to get a receipt email
        receipt_email = self.receipt_emails.first()
        if receipt_email:
            return receipt_email.email

        # If no receipt email, get an admin user's email
        user = self.users.filter(memberships__admin=True).first()
        if user:
            # Again, why not primary email?
            return user.email

        return None

    @property
    def user_full_name(self):
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
        return self.users.count() + self.invitations.get_pending_invitations().count()

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

    def customer(self):
        """Retrieve the customer from Stripe or create one if it doesn't exist"""
        customer, _ = self.customers.get_or_create()
        return customer

    def save_card(self, token, user):
        self.payment_failed = False
        self.save()
        self.customer().save_card(token)
        send_cache_invalidations("organization", self.uuid)

        self.change_logs.create(
            user=user,
            reason=ChangeLogReason.credit_card,
            credit_card=self.customer().card_display,
            to_max_users=self.max_users,
        )

    def remove_card(self):
        self.customer().remove_card()
        send_cache_invalidations("organization", self.uuid)

    @mproperty
    def plan(self):
        return self.plans.first()

    @mproperty
    def subscription(self):
        return self.subscriptions.first()

    def set_subscription(self, token, plan, max_users, user):
        # pylint: disable=import-outside-toplevel
        from squarelet.organizations.tasks import sync_wix

        if self.individual:
            max_users = 1

        if token or self.customer().card:
            payment_method = "card"
        else:
            # If we're missing a token and have no saved card,
            # we can only issue an invoice
            payment_method = "invoice"

        if token:
            # The user provided a new card: save it to the org's account
            self.save_card(token, user)

        # store so we can log
        from_plan, from_max_users = (self.plan, self.max_users)

        self.max_users = max_users
        self.save()
        if plan and plan.wix:
            for wix_user in self.users.all():
                sync_wix.delay(self.pk, plan.pk, wix_user.pk)

        if not self.plan and plan:
            # create a subscription going from no plan to plan
            customer = self.customer().stripe_customer
            if not customer.email:
                customer.email = self.email
                customer.save()
            self.subscriptions.start(
                organization=self, plan=plan, payment_method=payment_method
            )
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
        """The subscription was cancelled due to payment failure"""
        # Create change log entry
        self.change_logs.create(
            reason=ChangeLogReason.failed,
            from_plan=self.plan,
            from_max_users=self.max_users,
            to_max_users=self.max_users,
        )

        # Cancel subscription in Stripe if it exists
        if self.subscription and self.subscription.subscription_id:
            try:
                stripe.Subscription.delete(self.subscription.subscription_id)
                logger.info(
                    "Cancelled Stripe subscription %s for organization %s",
                    self.subscription.subscription_id,
                    self.uuid,
                )
            except stripe.error.StripeError as exc:
                logger.error(
                    "Failed to cancel Stripe subscription %s for organization %s: %s",
                    self.subscription.subscription_id,
                    self.uuid,
                    exc,
                    exc_info=sys.exc_info(),
                )

        # Delete local subscription record
        self.subscription.delete()

    def has_active_subscription(self):
        """Check if the organization has an active subscription"""
        return bool(self.subscription)

    def charge(
        self,
        amount,
        description,
        user,
        fee_amount=0,
        token=None,
        save_card=False,
        metadata=None,
    ):
        """Charge the organization and optionally save their credit card"""
        if save_card:
            self.save_card(token, user)
            token = None
        if metadata is None:
            metadata = {}
        charge = Charge.objects.make_charge(
            self, token, amount, fee_amount, description, metadata
        )
        return charge

    def set_receipt_emails(self, emails):
        new_emails = set(emails)
        old_emails = {r.email for r in self.receipt_emails.all()}
        self.receipt_emails.filter(email__in=old_emails - new_emails).delete()
        ReceiptEmail.objects.bulk_create(
            [ReceiptEmail(organization=self, email=e) for e in new_emails - old_emails]
        )

    def subscribe(self):
        """
        When an organization is first verified, subscribe all previous unverified
        members to the DocumentCloud onboarding journey via MailChimp
        """
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.users.models import User

        users = User.objects.filter(organizations=self).exclude(
            organizations__verified_journalist=True
        )
        subscribe_emails = [u.email for u in users]
        for email in subscribe_emails:
            mailchimp_journey(email, "verified")

    def is_hub_eligible(self):
        return bool(
            self.hub_eligible
            or self.groups.filter(hub_eligible=True).exists()
            or (self.parent and self.parent.is_hub_eligible)
        )

    def has_member_by_email(self, email):
        """Check if a user with an email is already a member of the organization."""
        return Membership.objects.filter(
            organization=self, user__email__iexact=email
        ).exists()

    def get_existing_open_invite(self, email):
        """Retrieve an open invitation (if any) for the given email."""
        return Invitation.objects.filter(
            organization=self,
            email__iexact=email,
            accepted_at__isnull=True,
            rejected_at__isnull=True,
            request=False,
        ).first()

    @transaction.atomic
    def merge(self, org, user):
        """Merge another organization into this one"""

        if org.subscriptions.exists():
            raise ValueError(f"{org} has an active subscription and may not be merged")
        if org.merged is not None:
            raise ValueError(
                f"{org} has already been merged, and may not be merged again"
            )
        if self.merged is not None:
            raise ValueError(
                f"{self} has already been merged, and may not be merged again"
            )
        if org.individual:
            raise ValueError(
                f"{org} is an individual organization and may not be merged"
            )
        if self.individual:
            raise ValueError(
                f"{self} is an individual organization and may not be merged"
            )

        org.charges.update(organization=self)

        org.memberships.exclude(user__in=self.users.all()).update(organization=self)
        org.memberships.all().delete()

        org.invitations.exclude(user__in=self.invitations.values("user")).update(
            organization=self
        )
        org.invitations.all().delete()

        org.receipt_emails.exclude(
            email__in=self.receipt_emails.values("email")
        ).update(organization=self)
        org.receipt_emails.all().delete()

        org.urls.exclude(url__in=self.urls.values("url")).update(organization=self)
        org.urls.all().delete()

        org.domains.exclude(domain__in=self.domains.values("domain")).update(
            organization=self
        )
        org.domains.all().delete()

        # only take other orgs parent if we do not have one
        if self.parent is None:
            self.parent = org.parent

        m2m_relations = ["private_plans", "children", "groups", "members", "subtypes"]
        for m2m in m2m_relations:
            getattr(self, m2m).add(*getattr(org, m2m).all())
            getattr(org, m2m).clear()

        org.merged = self
        org.merged_at = timezone.now()
        org.merged_by = user
        org.private = True

        org.save()
        self.save()


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

    created_at = AutoCreatedField(
        _("created_at"),
        null=True,
        blank=True,
        help_text=_("When this organization was created"),
    )

    class Meta:
        unique_together = ("user", "organization")
        ordering = ("user_id",)

    def __str__(self):
        return f"Membership: {self.user} in {self.organization}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user.uuid)
            )

    def delete(self, *args, **kwargs):
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
        _("email"),
        blank=True,
        help_text=_("The email address to send this invitation to"),
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

    def send(self):

        if self.request:
            send_mail(
                subject=_(f"{self.user} has requested to join {self.organization}"),
                template="organizations/email/join_request.html",
                organization=self.organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={"joiner": self.user},
            )
        else:
            send_mail(
                subject=_(f"Invitation to join {self.organization.name}"),
                template="organizations/email/invitation.html",
                to=[self.email],
                extra_context={"invitation": self},
            )

    @transaction.atomic
    def accept(self, user=None):
        """Accept the invitation"""
        # pylint: disable=import-outside-toplevel
        from squarelet.organizations.tasks import sync_wix

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
        if (
            self.organization.verified_journalist
            and not self.user.verified_journalist()
        ):
            mailchimp_journey(self.user.email, "verified")
        if not self.organization.has_member(self.user):
            Membership.objects.create(organization=self.organization, user=self.user)
            if self.organization.plan and self.organization.plan.wix:
                sync_wix.delay(
                    self.organization_id,
                    self.organization.plan.pk,
                    self.user.pk,
                )

    def reject(self):
        """Reject or revoke the invitation"""
        if self.accepted_at or self.rejected_at:
            raise ValueError("This invitation has already been closed")
        self.rejected_at = timezone.now()
        self.save()

    def get_name(self):
        """Returns the name or email if no name is set"""
        if self.user is not None and self.user.name:
            return f"{self.user.name} ({self.email})"
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
    email = models.EmailField(
        _("email"),
        help_text=_("The email address to send the receipt to"),
        db_collation="case_insensitive",
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
    credit_card = models.CharField(
        _("credit card"),
        max_length=255,
        default="",
        help_text=_("The updated credit card number"),
    )

    def describe(self):
        """A description of the change for digest emails"""
        if self.reason == ChangeLogReason.created:
            return (
                f"Created: {self.organization.name} - "
                f"Plan: {self.to_plan} with {self.to_max_users} users"
            )
        elif self.reason == ChangeLogReason.updated:
            return (
                f"Updated: {self.organization.name} - "
                f"From: Plan {self.from_plan} with {self.from_max_users} users - "
                f"To: Plan {self.to_plan} with {self.to_max_users} users"
            )
        elif self.reason == ChangeLogReason.failed:
            return (
                f"Payment Failed: {self.organization.name} - "
                f"Plan: {self.from_plan} with {self.from_max_users} users"
            )
        return "Other reason"


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

    class Meta:
        ordering = ("type",)

    def __str__(self):
        return f"{self.type.name} - {self.name}"


class OrganizationUrl(models.Model):
    """URLs associated with an organization"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="urls",
        help_text=_("The organization to associate the URL with"),
    )
    url = models.URLField(_("url"))


class OrganizationEmailDomain(models.Model):
    """Email Domains associated with an organization"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="domains",
        help_text=_("The organization to associate the email domain with"),
    )
    domain = models.CharField(_("domain"), max_length=255)
