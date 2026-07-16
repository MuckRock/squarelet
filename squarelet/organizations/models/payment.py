# Django
from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys
from datetime import datetime, time, timezone as dt_timezone
from functools import cached_property

# Third Party
import stripe
from autoslug import AutoSlugField

# Squarelet
from squarelet.core.mail import ORG_TO_RECEIPTS, send_mail
from squarelet.core.utils import is_production_env, mailchimp_journey
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.querysets import (
    ChargeQuerySet,
    EntitlementGrantQuerySet,
    EntitlementQuerySet,
    PlanQuerySet,
    SubscriptionQuerySet,
)

logger = logging.getLogger(__name__)

# pylint: disable=too-many-lines


def get_payment_brand(details):
    """Return the brand/institution name for a Stripe payment details sub-object.

    Handles both card (``details.brand``) and bank account
    (``details.bank_name``) sub-objects returned by ``Customer.payment_details``.
    """
    return getattr(details, "brand", None) or getattr(details, "bank_name", "")


class Customer(models.Model):
    """A customer on stripe"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="customers",
        unique=True,
    )

    customer_id = models.CharField(
        _("customer id"),
        max_length=255,
        unique=True,
        null=True,
        help_text=_("The customer's corresponding ID on stripe"),
    )

    payment_brand = models.CharField(max_length=64, blank=True, default="")
    payment_last4 = models.CharField(max_length=4, blank=True, default="")
    payment_exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    stripe_payment_method_id = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.organization.name}'s Customer"

    @cached_property
    def stripe_customer(self):
        """Retrieve the customer from Stripe or create one if it doesn't exist"""
        customer_service = get_payment_provider().get_customer_service()

        # first try to find an existing stripe customer
        if self.customer_id:
            try:
                stripe_customer = customer_service.retrieve(self.customer_id)
                if stripe_customer.name is None:
                    customer_service.modify(
                        stripe_customer.id, name=self.organization.user_full_name
                    )
                return stripe_customer
            except stripe.InvalidRequestError as exc:
                logger.error(
                    "[STRIPE CUSTOMER] Invalid Request Error "
                    "while fetching Customer %s "
                    "for Organization %s: %s. ",
                    self.customer_id,
                    self.organization.id,
                    exc,
                    exc_info=sys.exc_info(),
                )
                if exc.code == "resource_missing":
                    # When the customer doesn't exist on Stripe (deleted or wrong env),
                    # clear the invalid customer_id to prevent infinite network requests
                    self.customer_id = None
                    self.save()

        # if the stripe customer has not been created yet or has been removed,
        # create a new one.  Lock to avoid creating multiple in a race condition
        with transaction.atomic():
            customer = Customer.objects.filter(pk=self.pk).select_for_update().first()
            # first check if the customer was created in another thread
            if customer.customer_id:
                return customer.stripe_customer
            # create the customer on stripe
            stripe_customer = customer_service.create(
                description=customer.organization.name,
                email=customer.organization.email,
                name=customer.organization.user_full_name,
            )
            customer.customer_id = stripe_customer.id
            customer.save()
            return stripe_customer

    @cached_property
    def payment_method(self):
        """Retrieve the customer's default saved payment method or source, if any.

        Returns the raw Stripe PaymentMethod or legacy Source object.
        May be any payment method type (card, us_bank_account, etc.).
        """
        return (
            get_payment_provider()
            .get_customer_service()
            .get_payment_method(self.stripe_customer)
        )

    @cached_property
    def card(self):
        """Return card details if the default payment method is a card, else None.

        For card-specific logic only. Use payment_details for display-agnostic
        access to the payment method sub-object.
        """
        pm = self.payment_method
        if pm is None:
            return None
        if pm.object == "payment_method" and pm.type == "card":
            return pm.card
        if pm.object == "card":
            return pm
        return None

    @cached_property
    def payment_details(self):
        """Return the type-specific sub-object for the default payment method.

        Returns the appropriate sub-object exposing .last4 and type-specific
        fields, or None if no payment method is on file:
          - card PaymentMethod      → pm.card             (.brand, .last4)
          - bank account PM         → pm.us_bank_account  (.bank_name, .last4)
          - legacy Source/card      → source              (.brand, .last4)

        Warning: this calls the Stripe API. Use payment_method_display for
        latency-safe display from cached fields.
        """
        pm = self.payment_method
        if pm is None:
            return None
        if pm.object == "payment_method":
            if pm.type == "card":
                return pm.card
            if pm.type == "us_bank_account":
                return pm.us_bank_account
            return None
        if pm.object == "card":
            return pm
        return None

    @property
    def payment_method_display(self):
        if self.payment_brand and self.payment_last4:
            return f"{self.payment_brand}: x{self.payment_last4}"
        return ""

    PAYMENT_CACHE_FIELDS = [
        "payment_brand",
        "payment_last4",
        "payment_exp_month",
        "payment_exp_year",
        "stripe_payment_method_id",
    ]

    def save_payment_cache(self):
        self.save(update_fields=self.PAYMENT_CACHE_FIELDS)

    def clear_payment_cache(self):
        self.payment_brand = ""
        self.payment_last4 = ""
        self.payment_exp_month = None
        self.payment_exp_year = None
        self.stripe_payment_method_id = ""
        self.save_payment_cache()

    def save_card(self, token):
        """Save a new default card"""
        pm = (
            get_payment_provider()
            .get_customer_service()
            .save_card(self.stripe_customer, token)
        )
        if pm is not None:
            self.payment_brand = pm.card.brand or ""
            self.payment_last4 = pm.card.last4 or ""
            self.payment_exp_month = pm.card.exp_month
            self.payment_exp_year = pm.card.exp_year
            self.stripe_payment_method_id = pm.id or ""
            self.save_payment_cache()

    def remove_payment_method(self):
        """Remove the default payment method"""
        pm_id = self.stripe_payment_method_id
        if pm_id:
            customer_svc = get_payment_provider().get_customer_service()
            customer_svc.remove_payment_method(self.customer_id, pm_id)
            self.clear_payment_cache()

    def add_source(self, token):
        """Add a non-default source"""
        return (
            get_payment_provider()
            .get_customer_service()
            .add_source(self.stripe_customer, token)
        )


def _anchor_timestamp(anchor_date):
    """Return a UTC Unix timestamp for midnight on the given date."""
    aware = datetime.combine(anchor_date, time(0, 0), tzinfo=dt_timezone.utc)
    return int(aware.timestamp())


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

    # The cancelled flag is used to mark subscriptions that are ready for cancellation.
    # Cancellation happens at the end of the billing period; at that point,
    # the subscription is deleted from the database.
    cancelled = models.BooleanField(default=False)

    cancel_at = models.DateField(
        _("cancel at"),
        null=True,
        blank=True,
        help_text=_(
            "Date when Stripe will terminate this subscription. "
            "Set when cancel() is called. Null for free plans or legacy records."
        ),
    )

    quantity = models.PositiveIntegerField(
        _("quantity"),
        default=1,
        help_text=_(
            "Number of units of this plan's resources granted to the organization"
        ),
    )

    stripe_status = models.CharField(max_length=30, blank=True, default="")
    current_period_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("organization", "plan")
        ordering = ("plan",)

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Free"
        return f"Subscription: {self.organization} to {plan_name}"

    @cached_property
    def stripe_subscription(self):
        if self.subscription_id:
            return (
                get_payment_provider()
                .get_subscription_service()
                .retrieve(self.subscription_id)
            )
        return None

    def _cache_stripe_subscription_fields(self, stripe_sub):
        """Cache subscription status and period end from a Stripe subscription."""
        self.stripe_status = stripe_sub.status or ""
        ts = (
            get_payment_provider()
            .get_subscription_service()
            .get_current_period_end(stripe_sub)
        )
        self.current_period_end = (
            datetime.fromtimestamp(ts, tz=get_current_timezone()) if ts else None
        )

    def start(self, payment_method="card", billing_cycle_anchor=None):
        """Start the Stripe subscription. Returns the Stripe subscription object
        for paid plans, or None for free plans."""
        if self.stripe_subscription:
            logger.error(
                "Trying to start an existing subscription: %s %s",
                self.pk,
                self.subscription_id,
            )
            return None
        stripe_subscription = None
        if self.plan and not self.plan.free:
            # Annual plans support payment by invoice
            if self.plan.annual and payment_method == "invoice":
                billing = "send_invoice"
                days_until_due = 30
            else:
                billing = "charge_automatically"
                days_until_due = None

            anchor_ts = None
            if billing_cycle_anchor is not None:
                anchor_ts = _anchor_timestamp(billing_cycle_anchor)

            stripe_subscription = (
                get_payment_provider()
                .get_subscription_service()
                .create(
                    stripe_customer=self.organization.customer().stripe_customer,
                    plan_id=self.plan.stripe_id,
                    quantity=self.quantity,
                    billing=billing,
                    metadata={"action": f"Subscription ({self.plan})"},
                    days_until_due=days_until_due,
                    billing_cycle_anchor=anchor_ts,
                    cancel_at_period_end=not self.plan.auto_renew,
                )
            )
            self.subscription_id = stripe_subscription.id
            self._cache_stripe_subscription_fields(stripe_subscription)
            if not self.plan.auto_renew and self.current_period_end:
                self.cancel_at = self.current_period_end.date()
            # Save subscription before creating invoice
            self.save()

            # Check for 3DS/SCA on the first invoice payment.
            if stripe_subscription.status == "incomplete":
                self._check_3ds_action_required(stripe_subscription)

            # Create Invoice record synchronously; webhook is the fallback.
            self._sync_latest_invoice(stripe_subscription)

        # Trigger respective mailchimp journeys if this is the organization plan,
        # but only if the org doesn't already have another active subscription
        # granting the same entitlement (avoid duplicate journey triggers).
        if self.plan_id and self.plan.entitlements.filter(slug="organization").exists():
            already_has_org_entitlement = (
                self.organization.subscriptions.exclude(pk=self.pk)
                .filter(
                    plan__entitlements__slug="organization",
                )
                .exists()
            )
            if not already_has_org_entitlement:
                journey_key = (
                    "verified_premium_org"
                    if self.organization.verified_journalist
                    else "unverified_premium_org"
                )
                for user in self.organization.users.all():
                    mailchimp_journey(user.email, journey_key)

        # Slack notification for new subscription
        self.send_slack_notification("started")
        return stripe_subscription

    def _check_3ds_action_required(self, stripe_subscription):
        """Raise PaymentActionRequired if the first invoice requires 3DS authentication.

        invoice.confirmation_secret.client_secret has the form pi_xxx_secret_yyy;
        the PaymentIntent ID is the prefix before '_secret_'.
        """
        invoice_ref = stripe_subscription.latest_invoice
        if invoice_ref is None:
            return
        invoice_id = invoice_ref if isinstance(invoice_ref, str) else invoice_ref.id
        fresh_invoice = (
            get_payment_provider()
            .get_invoice_service()
            .retrieve(invoice_id, expand=["confirmation_secret"])
        )
        cs = fresh_invoice.confirmation_secret
        if cs and not isinstance(cs, str):
            client_secret = cs.client_secret
            if client_secret:
                pi_id = client_secret.split("_secret_")[0]
                raise PaymentActionRequired(client_secret, pi_id)

    def _sync_latest_invoice(self, stripe_subscription):
        """Create or update the local Invoice record for the subscription's
        first invoice.

        Logs and swallows errors so that a retrieval failure does not prevent the
        subscription from being saved — the webhook handler is the fallback.
        """
        invoice_ref = stripe_subscription.latest_invoice
        if not invoice_ref:
            return
        invoice_id = invoice_ref if isinstance(invoice_ref, str) else invoice_ref.id
        try:
            # Import here to avoid circular imports
            # pylint: disable=import-outside-toplevel
            # Squarelet
            from squarelet.organizations.models import Invoice  # Squarelet

            stripe_invoice = (
                get_payment_provider().get_invoice_service().retrieve(invoice_id)
            )
            _, created = Invoice.create_or_update_from_stripe(
                stripe_invoice, self.organization, self
            )
            logger.info(
                "[SUBSCRIPTION-START] Invoice %s synchronously: %s",
                "created" if created else "updated",
                stripe_invoice.id,
            )
        except stripe.StripeError as exc:
            logger.error(
                "[SUBSCRIPTION-START] Failed to retrieve invoice %s: %s",
                stripe_subscription.latest_invoice,
                exc,
                exc_info=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "[SUBSCRIPTION-START] Unexpected error creating invoice %s: %s",
                stripe_subscription.latest_invoice,
                exc,
                exc_info=True,
            )

    def cancel(self):
        if self.stripe_subscription:
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .cancel_at_period_end(self.stripe_subscription)
            )
            if updated:
                self._cache_stripe_subscription_fields(updated)
        self.cancelled = True
        if self.current_period_end:
            self.cancel_at = self.current_period_end.date()
        self.save()

        # Slack notification for cancellation
        self.send_slack_notification("cancelled")

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
            get_payment_provider().get_subscription_service().delete(
                self.stripe_subscription
            )
            self.subscription_id = None
            self.cancel_at = None
        elif not old_plan.free and not plan.free:
            # modify plan
            self.stripe_modify()

        self.save()

    def stripe_modify(self):
        """Update stripe subscription to match local subscription"""
        if self.stripe_subscription:
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .modify(
                    self.subscription_id,
                    cancel_at_period_end=not self.plan.auto_renew,
                    items=[
                        {
                            "id": self.stripe_subscription["items"]["data"][0].id,
                            "plan": self.plan.stripe_id,
                            "quantity": self.quantity,
                        }
                    ],
                    billing=(
                        "send_invoice" if self.plan.annual else "charge_automatically"
                    ),
                    metadata={"action": f"Subscription ({self.plan})"},
                    days_until_due=(30 if self.plan.annual else None),
                )
            )
            self.cancelled = False
            if updated:
                self._cache_stripe_subscription_fields(updated)
            if not self.plan.auto_renew and self.current_period_end:
                self.cancel_at = self.current_period_end.date()
            else:
                self.cancel_at = None
            self.save()

    def send_slack_notification(self, event, **kwargs):
        """Queue a Slack notification asynchronously for subscription events."""
        if not is_production_env():
            return

        if not self.plan.slack_webhook_url:
            return

        # pylint:disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.tasks import send_slack_notification

        # Link to the organization
        org_url = self.organization.get_absolute_url()
        domain = getattr(
            settings, "SQUARELET_URL", "https://accounts.muckrock.com"
        ).rstrip(
            "/"
        )  # avoid double slashes
        org_link = (
            f"<{domain}{org_url}|{self.organization.name}>"
            if org_url
            else self.organization.name
        )

        event_messages = {
            "started": {
                "subject": "New Subscription",
                "message": (
                    f"{org_link} has just subscribed to "
                    f"the *{self.plan.name}* plan."
                ),
            },
            "cancelled": {
                "subject": "Subscription Cancelled",
                "message": (
                    f"{org_link} has cancelled their subscription "
                    f"to the *{self.plan.name}* plan."
                ),
            },
        }

        if event not in event_messages:
            logger.warning("Unknown subscription event: %s", event)
            return

        event_data = event_messages[event]
        subject = event_data["subject"]
        message = event_data["message"]

        # Build the base section block
        section_block = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{subject}*\n\n{message}"},
            "accessory": {
                "type": "image",
                "image_url": self.organization.avatar_url,
                "alt_text": f"{self.organization.name} avatar",
            },
        }

        slack_message = {
            "text": f"{subject}\n\n{message}",  # Fallback text for notifications
            "blocks": [section_block],
        }

        send_slack_notification.delay(
            self.plan.slack_webhook_url, subject, slack_message
        )


class Plan(models.Model):
    """Plans that organizations can subscribe to"""

    objects = PlanQuerySet.as_manager()

    name = models.CharField(_("name"), max_length=255, help_text=_("The plan's name"))
    slug = AutoSlugField(
        _("slug"),
        populate_from="name",
        unique=True,
        editable=True,
        help_text=_("A unique slug to identify the plan"),
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
    auto_renew = models.BooleanField(
        _("auto renew"),
        default=True,
        help_text=_(
            "Automatically renew subscriptions to this plan at the end of each "
            "billing period. Disable for plans, such as high-value annual plans, "
            "that should not automatically renew."
        ),
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
    # remove
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

    slack_webhook_url = models.URLField(
        _("Slack webhook URL"),
        blank=True,
        null=True,
        help_text=_(
            "Webhook URL to notify when an organization subscribes to this plan"
        ),
    )

    # do we need to sync users on this plan to wix?
    wix = models.BooleanField(default=False)

    benefits = models.JSONField(
        _("benefits"),
        default=list,
        help_text=_("List of benefits included with this plan"),
        blank=True,
    )
    short_description = models.TextField(
        _("description"),
        blank=True,
        help_text=_("A short description of the plan, used in lists"),
    )
    description = models.TextField(
        _("description"),
        blank=True,
        help_text=_("Detailed description of the plan, in Markdown"),
    )

    class Meta:
        ordering = ("slug",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("plan_detail", kwargs={"pk": self.pk, "slug": self.slug})

    @property
    def free(self):
        return self.base_price == 0 and self.price_per_user == 0

    def requires_payment(self):
        """Does this plan require immediate payment?
        Free plans never require payment
        Annual payments are invoiced and do not require payment at time of purchase
        """
        return not self.free and not self.annual

    def has_available_slots(self):
        """Check if new subscriptions are allowed for this plan"""
        # Only Sunlight plans have subscription limits
        if self.slug.startswith("sunlight-") and self.wix:
            current_count = Subscription.objects.sunlight_active_count()
            return current_count < settings.MAX_SUNLIGHT_SUBSCRIPTIONS
        return True

    def cost(self, users):
        return (
            self.base_price + max(users - self.minimum_users, 0) * self.price_per_user
        )

    @property
    def is_sunlight_plan(self):
        """Check if this is a Sunlight Research Center plan"""
        return self.slug.startswith("sunlight-")

    @property
    def nonprofit_variant_slug(self):
        """Get the nonprofit variant slug for this plan"""
        if self.slug.startswith("sunlight-nonprofit-"):
            return self.slug  # Already a nonprofit variant
        elif self.slug.startswith("sunlight-"):
            # Convert sunlight-essential -> sunlight-nonprofit-essential
            # Convert sunlight-essential-annual -> sunlight-nonprofit-essential-annual
            return self.slug.replace("sunlight-", "sunlight-nonprofit-", 1)
        return None

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
                get_payment_provider().get_plan_service().create(
                    plan_id=self.stripe_id,
                    currency="usd",
                    interval="year" if self.annual else "month",
                    product={"name": self.name, "unit_label": "Seats"},
                    **kwargs,
                )
            except stripe.InvalidRequestError:  # pragma: no cover
                # if the plan already exists, just skip
                pass

    def delete_stripe_plan(self):
        """Remove a stripe plan"""
        try:
            plan_service = get_payment_provider().get_plan_service()
            plan = plan_service.retrieve(self.stripe_id)
            # We also want to remove the associated product
            product = plan_service.retrieve_product(plan.product)
            plan_service.delete(plan)
            plan_service.delete_product(product)
        except stripe.InvalidRequestError:
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

    description = models.CharField(
        _("description"),
        max_length=255,
        help_text=_("A description of what the charge was for"),
    )

    metadata = models.JSONField(_("metadata"), default=dict)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"${self.amount / 100:.2f} charge to {self.organization.name}"

    def get_absolute_url(self):
        return reverse("organizations:charge", kwargs={"pk": self.pk})

    @cached_property
    def charge(self):
        return get_payment_provider().get_charge_service().retrieve(self.charge_id)

    @property
    def amount_dollars(self):
        return self.amount / 100.0

    def send_receipt(self):
        """Send receipt"""
        current_emails = list(
            self.organization.receipt_emails.values_list("email", flat=True)
        )
        existing = self.metadata.get("receipt_emails", [])
        seen = set(existing)
        merged = list(existing) + [e for e in current_emails if e not in seen]
        self.metadata["receipt_emails"] = merged
        self.save(update_fields=["metadata"])
        plan = Plan.objects.filter(name=self.metadata.get("plan")).first()

        send_mail(
            subject=_("Receipt"),
            template="organizations/email/receipt.html",
            organization=self.organization,
            organization_to=ORG_TO_RECEIPTS,
            extra_context={
                "charge": self,
                "plan": plan,
                "receipt_emails": current_emails,
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
    resources = models.JSONField(
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


class EntitlementGrant(models.Model):
    """Grants Entitlements to organizations, explicitly or by rule."""

    name = models.CharField(_("name"), max_length=255)
    description = models.TextField(_("description"), blank=True, default="")

    entitlements = models.ManyToManyField(
        verbose_name=_("entitlements"),
        to="organizations.Entitlement",
        related_name="grants",
        help_text=_("Entitlements this grant extends"),
    )
    organizations = models.ManyToManyField(
        verbose_name=_("organizations"),
        to="organizations.Organization",
        related_name="entitlement_grants",
        blank=True,
        help_text=_("Organizations explicitly granted these entitlements"),
    )

    require_verified = models.BooleanField(
        _("require verified"),
        default=False,
        help_text=_("Match organizations whose verified_journalist=True"),
    )
    require_active_subscription = models.BooleanField(
        _("require active subscription"),
        default=False,
        help_text=_("Match organizations with at least one active subscription"),
    )

    for_individuals = models.BooleanField(
        _("for individuals"),
        default=True,
        help_text=_("Apply this grant to individual organizations"),
    )
    for_groups = models.BooleanField(
        _("for groups"),
        default=True,
        help_text=_("Apply this grant to non-individual organizations"),
    )

    active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Inactive grants do not apply to any organization"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EntitlementGrantQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "name")

    def __str__(self):
        return self.name

    def matches(self, org):
        if not self.active:
            return False
        # Org-type filter applies to both explicit and rule-based matches.
        if org.individual and not self.for_individuals:
            return False
        if not org.individual and not self.for_groups:
            return False
        # Uses `.all()` so a prefetched `organizations` relation is reused.
        if self.organizations.filter(pk=org.pk).exists():
            return True
        checks = []
        if self.require_verified:
            checks.append(bool(org.verified_journalist))
        if self.require_active_subscription:
            checks.append(org.has_active_subscription())
        if not checks:
            return False
        return all(checks)

    def matching_organizations(self):
        """Return queryset of organizations this grant currently matches.

        Reverse of `matches(org)`. Used by the celery refresh task and by signal
        handlers to compute the set of orgs whose cache must be invalidated.
        """
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.models.organization import Organization

        if not self.active:
            return Organization.objects.none()

        if self.for_individuals and self.for_groups:
            eligible = Organization.objects.all()
        elif self.for_individuals:
            eligible = Organization.objects.filter(individual=True)
        elif self.for_groups:
            eligible = Organization.objects.filter(individual=False)
        else:
            return Organization.objects.none()

        explicit_q = Q(entitlement_grants=self)

        rule_clauses = []
        if self.require_verified:
            rule_clauses.append(Q(verified_journalist=True))
        if self.require_active_subscription:
            # Mirrors org.has_active_subscription() = bool(subscriptions.first())
            rule_clauses.append(Q(subscriptions__isnull=False))

        if rule_clauses:
            rule_q = rule_clauses[0]
            for clause in rule_clauses[1:]:
                rule_q &= clause
            return eligible.filter(explicit_q | rule_q).distinct()
        return eligible.filter(explicit_q)


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
