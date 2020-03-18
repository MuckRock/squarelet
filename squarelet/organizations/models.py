# Django
from django.conf import settings
from django.contrib.postgres.fields import CIEmailField
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

# Standard Library
import logging
import uuid

# Third Party
import stripe
from autoslug import AutoSlugField
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.mail import ORG_TO_ADMINS, ORG_TO_RECEIPTS, send_mail
from squarelet.core.mixins import AvatarMixin
from squarelet.core.utils import file_path
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.choices import ChangeLogReason, StripeAccounts
from squarelet.organizations.querysets import (
    ChargeQuerySet,
    EntitlementQuerySet,
    InvitationQuerySet,
    MembershipQuerySet,
    OrganizationQuerySet,
    PlanQuerySet,
    SubscriptionQuerySet,
)

stripe.api_version = "2018-09-24"

DEFAULT_AVATAR = static("images/avatars/organization.png")

logger = logging.getLogger(__name__)


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

    # XXX remove these
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
    # XXX remove these

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

    # Book keeping
    max_users = models.IntegerField(
        _("maximum users"),
        default=5,
        help_text=_("The maximum number of users in this organization"),
    )
    # XXX move this to subscription
    update_on = models.DateField(
        _("date update"),
        null=True,
        blank=True,
        help_text=_("Date when monthly requests are restored"),
    )

    # stripe
    # XXX move to customer
    customer_id = models.CharField(
        _("customer id"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("The organization's corresponding ID on stripe"),
    )
    # XXX move to subscription
    subscription_id = models.CharField(
        _("subscription id"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("The organization's corresponding subscription ID on stripe"),
    )
    # XXX should this be moved to customer?
    # XXX should have better card management functionality
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

        return self.users.filter(memberships__admin=True).first().email

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
        try:
            customer = self.customers.get(stripe_account=stripe_account)
        except Customer.DoesNotExist:
            stripe_customer = stripe.Customer.create(
                description=self.name,
                email=self.email,
                api_key=settings.STRIPE_SECRET_KEYS[stripe_account],
            )
            customer = self.customers.create(
                customer_id=stripe_customer.id, stripe_account=stripe_account
            )
        return customer

    def save_card(self, token, stripe_account):
        self.payment_failed = False
        self.save()
        self.customer(stripe_account).save_card(token)
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
        stripe_account=StripeAccounts.muckrock,
    ):
        """Charge the organization and optionally save their credit card"""
        if save_card:
            self.save_card(token, stripe_account)
            token = None
        charge = Charge.objects.make_charge(
            self, token, amount, fee_amount, description, stripe_account
        )
        return charge

    def set_receipt_emails(self, emails):
        new_emails = set(emails)
        old_emails = {r.email for r in self.receipt_emails.all()}
        self.receipt_emails.filter(email__in=old_emails - new_emails).delete()
        ReceiptEmail.objects.bulk_create(
            [ReceiptEmail(organization=self, email=e) for e in new_emails - old_emails]
        )


class Customer(models.Model):
    """A customer on stripe"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="customers",
    )
    stripe_account = models.PositiveSmallIntegerField(
        _("stripe account"),
        choices=StripeAccounts.choices,
        help_text=_("Which company's stripe account"),
    )

    customer_id = models.CharField(
        _("customer id"),
        max_length=255,
        unique=True,
        help_text=_("The customer's corresponding ID on stripe"),
    )

    class Meta:
        unique_together = ("organization", "stripe_account")

    def __str__(self):
        return (
            f"{self.organization.name}'s {self.get_stripe_account_display()} Customer"
        )

    @mproperty
    def stripe_customer(self):
        """Retrieve the customer from Stripe or create one if it doesn't exist"""
        try:
            stripe_customer = stripe.Customer.retrieve(
                self.customer_id,
                api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account],
            )
        except stripe.error.InvalidRequestError:
            stripe_customer = stripe.Customer.create(
                description=self.organization.name,
                email=self.organization.email,
                api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account],
            )
            self.customer_id = stripe_customer.id
            self.save()
        return stripe_customer

    @mproperty
    def card(self):
        """Retrieve the customer's default credit card on file, if there is one"""
        if self.stripe_customer.default_source:
            source = self.stripe_customer.sources.retrieve(
                self.stripe_customer.default_source
            )
            if source.object == "card":
                return source
            else:
                return None
        else:
            return None

    @property
    def card_display(self):
        if self.card:
            return f"{self.card.brand}: {self.card.last4}"
        else:
            return ""

    def save_card(self, token):
        """Save a new default card"""
        self.stripe_customer.source = token
        self.stripe_customer.save()

    def add_source(self, token):
        """Add a non-default source"""
        return self.stripe_customer.sources.create(source=token)


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


class Subscription(models.Model):
    """Through table for organization plans"""

    objects = SubscriptionQuerySet.as_manager()

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        verbose_name=_("plan"),
        to="organizations.Plan",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )

    subscription_id = models.CharField(
        _("subscription id"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("The subscription ID on stripe"),
    )
    update_on = models.DateField(
        _("date update"), help_text=_("Date when monthly resources are restored")
    )

    cancelled = models.BooleanField(default=False)

    class Meta:
        unique_together = ("organization", "plan")
        ordering = ("plan",)

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Free"
        return f"Subscription: {self.organization} to {plan_name}"

    @mproperty
    def stripe_subscription(self):
        if self.subscription_id:
            try:
                return stripe.Subscription.retrieve(
                    self.subscription_id,
                    api_key=settings.STRIPE_SECRET_KEYS[self.plan.stripe_account],
                )
            except stripe.error.InvalidRequestError:  # pragma: no cover
                return None
        else:
            return None

    def start(self):
        if self.stripe_subscription:
            logger.error(
                "Trying to start an existing subscription: %s %s",
                self.pk,
                self.subscription_id,
            )
            return
        if self.plan and not self.plan.free:
            stripe_subscription = self.organization.customer(
                self.plan.stripe_account
            ).stripe_customer.subscriptions.create(
                items=[
                    {
                        "plan": self.plan.stripe_id,
                        "quantity": self.organization.max_users,
                    }
                ],
                billing="send_invoice" if self.plan.annual else "charge_automatically",
                days_until_due=30 if self.plan.annual else None,
            )
            self.subscription_id = stripe_subscription.id

    def cancel(self):
        if self.stripe_subscription:
            self.stripe_subscription.cancel_at_period_end = True
            self.stripe_subscription.save()

        self.cancelled = True
        self.save()

    def modify(self, plan):
        """Modify an existing plan
        Note - this should never be used to switch from a MR to a PP plan or vice versa
        """
        old_plan = self.plan
        self.plan = plan
        self.save()

        if old_plan.free and not plan.free:
            # start subscription on stripe
            self.start()
        elif not old_plan.free and plan.free:
            # cancel subscription on stripe
            self.stripe_subscription.delete()
            self.subscription_id = None
        elif not old_plan.free and not plan.free:
            # modify plan
            self.stripe_modify()

        self.save()

    def stripe_modify(self):
        """Update stripe subscription to match local subscription"""
        if self.stripe_subscription:
            stripe.Subscription.modify(
                self.subscription_id,
                cancel_at_period_end=False,
                items=[
                    {
                        # pylint: disable=unsubscriptable-object
                        "id": self.stripe_subscription["items"]["data"][0].id,
                        "plan": self.plan.stripe_id,
                        "quantity": self.organization.max_users,
                    }
                ],
                billing="send_invoice" if self.plan.annual else "charge_automatically",
                days_until_due=30 if self.plan.annual else None,
                api_key=settings.STRIPE_SECRET_KEYS[self.plan.stripe_account],
            )


class Plan(models.Model):
    """Plans that organizations can subscribe to"""

    objects = PlanQuerySet.as_manager()

    name = models.CharField(_("name"), max_length=255, help_text=_("The plan's name"))
    slug = AutoSlugField(
        _("slug"),
        populate_from="name",
        unique=True,
        help_text=_("A uinique slug to identify the plan"),
    )

    minimum_users = models.PositiveSmallIntegerField(
        _("minimum users"),
        default=1,
        help_text=_("The minimum number of users allowed on this plan"),
    )
    base_price = models.PositiveSmallIntegerField(
        _("base price"),
        default=0,
        help_text=_(
            "The price per month for this plan with the minimum number of users"
        ),
    )
    price_per_user = models.PositiveSmallIntegerField(
        _("price per user"),
        default=0,
        help_text=_("The additional cost per month per user over the minimum"),
    )

    public = models.BooleanField(
        _("public"),
        default=False,
        help_text=_("Is this plan available for anybody to sign up for?"),
    )
    annual = models.BooleanField(
        _("annual"),
        default=False,
        help_text=_("Invoice this plan annually instead of charging monthly"),
    )
    for_individuals = models.BooleanField(
        _("for individuals"),
        default=True,
        help_text=_("Is this plan usable for individual organizations?"),
    )
    for_groups = models.BooleanField(
        _("for groups"),
        default=True,
        help_text=_("Is this plan usable for non-individual organizations?"),
    )
    # XXX remove
    requires_updates = models.BooleanField(
        _("requires updates"),
        default=True,
        help_text=_(
            "Specifies if this plan requires monthly updates, in order for client "
            "sites to restore montly consumable resources"
        ),
    )

    entitlements = models.ManyToManyField(
        verbose_name=_("entitlements"),
        to="organizations.Entitlement",
        related_name="plans",
        help_text=_("Entitlements granted by this plan"),
        blank=True,
    )

    private_organizations = models.ManyToManyField(
        verbose_name=_("private organizations"),
        to="organizations.Organization",
        related_name="private_plans",
        help_text=_(
            "For private plans, organizations which should have access to this plan"
        ),
        blank=True,
    )

    stripe_account = models.PositiveSmallIntegerField(
        _("stripe account"),
        choices=StripeAccounts.choices,
        default=StripeAccounts.muckrock,
        help_text=_(
            "Which company's stripe account is used for subscrpitions to this plan"
        ),
    )

    class Meta:
        ordering = ("slug",)

    def __str__(self):
        return self.name

    @property
    def free(self):
        return self.base_price == 0 and self.price_per_user == 0

    def requires_payment(self):
        """Does this plan require immediate payment?
        Free plans never require payment
        Annual payments are invoiced and do not require payment at time of purchase
        """
        return not self.free and not self.annual

    def cost(self, users):
        return (
            self.base_price + max(users - self.minimum_users, 0) * self.price_per_user
        )

    @property
    def stripe_id(self):
        """Namespace the stripe ID to not conflict with previous plans we have made"""
        return f"squarelet_plan_{self.slug}"

    def make_stripe_plan(self):
        """Create the plan on stripe"""
        if not self.free:
            try:
                # set up the pricing for groups and individuals
                # convert dollar amounts to cents for stripe
                if self.for_groups:
                    kwargs = {
                        "billing_scheme": "tiered",
                        "tiers": [
                            {
                                "flat_amount": 100 * self.base_price,
                                "up_to": self.minimum_users,
                            },
                            {"unit_amount": 100 * self.price_per_user, "up_to": "inf"},
                        ],
                        "tiers_mode": "graduated",
                    }
                else:
                    kwargs = {
                        "billing_scheme": "per_unit",
                        "amount": 100 * self.base_price,
                    }
                stripe.Plan.create(
                    id=self.stripe_id,
                    currency="usd",
                    interval="year" if self.annual else "month",
                    product={"name": self.name, "unit_label": "Seats"},
                    api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account],
                    **kwargs,
                )
            except stripe.error.InvalidRequestError:  # pragma: no cover
                # if the plan already exists, just skip
                pass

    def delete_stripe_plan(self):
        """Remove a stripe plan"""
        try:
            plan = stripe.Plan.retrieve(
                id=self.stripe_id,
                api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account],
            )
            # We also want to remove the associated product
            product = stripe.Product.retrieve(
                id=plan.product,
                api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account],
            )
            plan.delete()
            product.delete()
        except stripe.error.InvalidRequestError:
            # if the plan or product do not exist, just skip
            pass


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


class Charge(models.Model):
    """A payment charged to an organization through Stripe"""

    objects = ChargeQuerySet.as_manager()

    amount = models.PositiveIntegerField(_("amount"), help_text=_("Amount in cents"))
    fee_amount = models.PositiveSmallIntegerField(
        _("fee amount"), default=0, help_text=_("Fee percantage")
    )
    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        related_name="charges",
        on_delete=models.PROTECT,
        help_text=_("The organization charged"),
    )
    created_at = models.DateTimeField(
        _("created at"), help_text=_("When the charge was created")
    )
    charge_id = models.CharField(
        _("charge_id"),
        max_length=255,
        unique=True,
        help_text=_("The strip ID for the charge"),
    )
    stripe_account = models.PositiveSmallIntegerField(
        _("stripe account"),
        choices=StripeAccounts.choices,
        default=StripeAccounts.muckrock,
        help_text=_("Which company's stripe account is used for this charge"),
    )

    description = models.CharField(
        _("description"),
        max_length=255,
        help_text=_("A description of what the charge was for"),
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"${self.amount / 100:.2f} charge to {self.organization.name}"

    def get_absolute_url(self):
        return reverse("organizations:charge", kwargs={"pk": self.pk})

    @mproperty
    def charge(self):
        return stripe.Charge.retrieve(
            self.charge_id, api_key=settings.STRIPE_SECRET_KEYS[self.stripe_account]
        )

    @property
    def amount_dollars(self):
        return self.amount / 100.0

    def send_receipt(self):
        """Send receipt"""
        send_mail(
            subject=_("Receipt"),
            template="organizations/email/receipt.html",
            organization=self.organization,
            organization_to=ORG_TO_RECEIPTS,
            extra_context={
                "charge": self,
                "individual_subscription": self.description == "Professional",
                "group_subscription": self.description.startswith("Organization"),
            },
        )

    def items(self):
        if self.fee_amount:
            fee_multiplier = 1 + (self.fee_amount / 100.0)
            base_price = int(self.amount / fee_multiplier)
            fee_price = self.amount - base_price
            return [
                {"name": self.description, "price": base_price / 100},
                {"name": "Processing Fee", "price": fee_price / 100},
            ]
        else:
            return [{"name": self.description, "price": self.amount_dollars}]


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


def entitlement_slug(instance):
    return f"{instance.client.name}-{instance.name}"


class Entitlement(models.Model):
    """Grants access to some service for a given client"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The entitlement's name")
    )
    slug = AutoSlugField(
        _("slug"),
        populate_from=entitlement_slug,
        unique=True,
        help_text=_("A unique slug to identify the plan"),
    )
    client = models.ForeignKey(
        verbose_name=_("client"),
        to="oidc_provider.Client",
        on_delete=models.CASCADE,
        related_name="entitlements",
        help_text=_("Client this entitlement grants access to"),
    )
    description = models.TextField(
        _("description"),
        help_text=_("A brief description of the service this grants access to"),
    )

    objects = EntitlementQuerySet.as_manager()

    class Meta:
        unique_together = ("name", "client")
        ordering = ("slug",)

    def __str__(self):
        return f"{self.client} - {self.name}"

    @property
    def public(self):
        return self.plans.filter(public=True).exists()
