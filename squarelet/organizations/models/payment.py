# Django
from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Standard Library
import logging

# Third Party
import stripe
from autoslug import AutoSlugField
from memoize import mproperty

# Squarelet
from squarelet.core.mail import ORG_TO_RECEIPTS, send_mail
from squarelet.organizations.choices import StripeAccounts
from squarelet.organizations.querysets import (
    ChargeQuerySet,
    EntitlementQuerySet,
    PlanQuerySet,
    SubscriptionQuerySet,
)

stripe.api_version = "2018-09-24"
logger = logging.getLogger(__name__)


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


def entitlement_slug(instance):
    return f"{instance.client.name}-{instance.name}"


class Entitlement(models.Model):
    """Grants access to some service for a given client"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The entitlement's name")
    )
    client = models.ForeignKey(
        verbose_name=_("client"),
        to="oidc_provider.Client",
        on_delete=models.CASCADE,
        related_name="entitlements",
        help_text=_("Client this entitlement grants access to"),
    )
    slug = AutoSlugField(
        _("slug"),
        populate_from="name",
        unique_with="client",
        help_text=_("A slug to identify the plan"),
    )
    description = models.TextField(
        _("description"),
        help_text=_("A brief description of the service this grants access to"),
    )
    resources = JSONField(
        _("resources"),
        default=dict,
        help_text=_(
            "Allows clients to track metadata for the resources this entitlement grants"
        ),
    )

    objects = EntitlementQuerySet.as_manager()

    class Meta:
        unique_together = [("name", "client"), ("slug", "client")]
        ordering = ("slug",)

    def __str__(self):
        return f"{self.client} - {self.name}"

    @property
    def public(self):
        return self.plans.filter(public=True).exists()
