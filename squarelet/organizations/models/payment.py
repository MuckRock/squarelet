# Django
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys
from datetime import datetime
from functools import cached_property

# Third Party
import stripe
from autoslug import AutoSlugField

# Squarelet
from squarelet.core.storage import private_storage
from squarelet.core.utils import is_production_env, mailchimp_journey
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.querysets import (
    ChargeQuerySet,
    EntitlementGrantQuerySet,
    EntitlementQuerySet,
    PlanQuerySet,
    SubscriptionItemQuerySet,
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

    def default_payment_method_obj(self):
        """Return the default PaymentMethod object, or None.

        Caches the result on the instance so multiple property
        accesses in the same request only hit the DB once.  The
        cache is cleared automatically by ``save_payment_cache``
        and ``clear_payment_cache``.
        """
        sentinel = object()
        cached = getattr(self, "_default_pm_cache", sentinel)
        if cached is not sentinel:
            return cached
        result = self.payment_methods.filter(is_default=True).first()
        self._default_pm_cache = result
        return result

    def _invalidate_pm_cache(self):
        try:
            del self._default_pm_cache
        except AttributeError:
            pass

    @property
    def payment_brand(self):
        pm = self.default_payment_method_obj()
        return pm.brand if pm else ""

    @property
    def payment_last4(self):
        pm = self.default_payment_method_obj()
        return pm.last4 if pm else ""

    @property
    def payment_exp_month(self):
        pm = self.default_payment_method_obj()
        return pm.exp_month if pm else None

    @property
    def payment_exp_year(self):
        pm = self.default_payment_method_obj()
        return pm.exp_year if pm else None

    @property
    def stripe_payment_method_id(self):
        pm = self.default_payment_method_obj()
        return pm.stripe_id if pm else ""

    @property
    def payment_method_display(self):
        pm = self.default_payment_method_obj()
        if pm:
            return pm.display
        return ""

    def save_payment_cache(self, details, stripe_id, method_type="card"):
        """Create or update the default PaymentMethod.

        ``details`` is the type-specific sub-object from a Stripe
        PaymentMethod or legacy Source (e.g. ``pm.card``,
        ``pm.us_bank_account``, or the Source itself).
        """
        valid_types = {c[0] for c in PaymentMethod.MethodType.choices}
        if method_type not in valid_types:
            method_type = PaymentMethod.MethodType.OTHER
        brand = get_payment_brand(details)
        last4 = getattr(details, "last4", "")
        exp_month = getattr(details, "exp_month", None)
        exp_year = getattr(details, "exp_year", None)
        pm = self.default_payment_method_obj()
        if pm:
            pm.method_type = method_type
            pm.brand = brand
            pm.last4 = last4
            pm.exp_month = exp_month
            pm.exp_year = exp_year
            pm.stripe_id = stripe_id
            pm.save()
        else:
            self.payment_methods.filter(is_default=True).update(is_default=False)
            PaymentMethod.objects.update_or_create(
                customer=self,
                is_default=True,
                defaults={
                    "method_type": method_type,
                    "brand": brand,
                    "last4": last4,
                    "exp_month": exp_month,
                    "exp_year": exp_year,
                    "stripe_id": stripe_id,
                },
            )
        self._invalidate_pm_cache()

    def clear_payment_cache(self):
        """Delete the default PaymentMethod."""
        self.payment_methods.filter(is_default=True).delete()
        self._invalidate_pm_cache()

    def save_card(self, token):
        """Save a new default card"""
        pm = (
            get_payment_provider()
            .get_customer_service()
            .save_card(self.stripe_customer, token)
        )
        if pm is not None:
            self.save_payment_cache(pm.card, pm.id or "")

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


class Subscription(models.Model):
    """A subscription on Stripe.

    One row per Stripe subscription; its lines are SubscriptionItems.  Stripe
    requires every item on a subscription to share a billing interval and a
    collection method, so an organization needs a separate subscription for
    each combination it holds - a monthly MuckRock plan and an annual Sunlight
    plan cannot sit on the same one.  That is what the uniqueness constraint
    below encodes.

    Fields here are subscription-level: status, period end and cancellation
    apply to every item at once.  Keeping them in one place means a renewal
    webhook updates a single row rather than fanning out across items that
    could then disagree.
    """

    INTERVAL_CHOICES = [
        ("monthly", _("Monthly")),
        ("annual", _("Annual")),
    ]
    COLLECTION_CHOICES = [
        ("charge_automatically", _("Charge automatically")),
        ("send_invoice", _("Send invoice")),
    ]

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscription_id = models.CharField(
        _("subscription id"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "The subscription ID on stripe.  Blank for subscriptions that "
            "never reach Stripe, which is every comped one."
        ),
    )
    interval = models.CharField(
        _("interval"),
        max_length=20,
        choices=INTERVAL_CHOICES,
        default="monthly",
        help_text=_("Billing interval shared by every item"),
    )
    collection_method = models.CharField(
        _("collection method"),
        max_length=30,
        choices=COLLECTION_CHOICES,
        default="charge_automatically",
        help_text=_("How Stripe collects payment, shared by every item"),
    )

    # The cancelled flag marks a subscription as ready for cancellation.
    # Cancellation happens at the end of the billing period; at that point the
    # record is deleted.
    cancelled = models.BooleanField(default=False)
    cancel_at = models.DateField(
        _("cancel at"),
        null=True,
        blank=True,
        help_text=_(
            "Date when Stripe will terminate this subscription.  Set when "
            "cancel() is called.  Null for free subscriptions."
        ),
    )
    stripe_status = models.CharField(max_length=30, blank=True, default="")
    current_period_end = models.DateTimeField(null=True, blank=True)

    plans = models.ManyToManyField(
        verbose_name=_("plans"),
        to="organizations.Plan",
        through="organizations.SubscriptionItem",
        related_name="subscriptions",
        help_text=_("Plans billed on this subscription"),
        blank=True,
    )

    @cached_property
    def stripe_subscription(self):
        if self.subscription_id:
            return (
                get_payment_provider()
                .get_subscription_service()
                .retrieve(self.subscription_id)
            )
        return None

    @property
    def free(self):
        """A subscription costs nothing when every line does."""
        return all(item.plan is None or item.plan.free for item in self.items.all())

    @property
    def auto_renew(self):
        """Renew unless some line says otherwise."""
        return all(item.plan.auto_renew for item in self.items.all())

    def stripe_items(self, include_ids=False):
        """Stripe line specs for every item on this subscription.

        Pass include_ids when modifying an existing subscription: Stripe needs
        each line's own id to update it in place rather than replace it.
        """
        specs = []
        for item in self.items.select_related("plan"):
            spec = {"plan": item.plan.stripe_id, "quantity": item.quantity}
            if include_ids and item.stripe_item_id:
                spec["id"] = item.stripe_item_id
            specs.append(spec)
        return specs

    def cache_stripe_subscription_fields(self, stripe_sub):
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

    def start(self, payment_method="card", anchor_day=None):
        """Create this subscription on Stripe, with all of its items.

        Returns the Stripe subscription for paid subscriptions, or None when
        every line is free - those never reach Stripe at all.
        """
        if self.stripe_subscription:
            logger.error(
                "Trying to start an existing subscription: %s %s",
                self.pk,
                self.subscription_id,
            )
            return None
        if self.free:
            return None

        # Annual subscriptions support payment by invoice
        if self.interval == "annual" and payment_method == "invoice":
            billing = "send_invoice"
            days_until_due = 30
        else:
            billing = "charge_automatically"
            days_until_due = None
        self.collection_method = billing

        stripe_subscription = (
            get_payment_provider()
            .get_subscription_service()
            .create(
                stripe_customer=self.organization.customer().stripe_customer,
                items=self.stripe_items(),
                billing=billing,
                metadata={"action": f"Subscription ({self.organization})"},
                days_until_due=days_until_due,
                anchor_day=anchor_day,
                cancel_at_period_end=not self.auto_renew,
            )
        )
        self.subscription_id = stripe_subscription.id
        self.cache_stripe_subscription_fields(stripe_subscription)
        if not self.auto_renew and self.current_period_end:
            self.cancel_at = self.current_period_end.date()
        # Save before creating the invoice
        self.save()

        # Check for 3DS/SCA on the first invoice payment.
        if stripe_subscription.status == "incomplete":
            self._check_3ds_action_required(stripe_subscription)

        self._sync_latest_invoice(stripe_subscription)
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
                stripe_invoice.to_dict(), self.organization, self
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
                self.cache_stripe_subscription_fields(updated)
        self.cancelled = True
        if self.current_period_end:
            self.cancel_at = self.current_period_end.date()
        self.save()

        # The notification names a plan, so it belongs to the lines, not to
        # the subscription that carries them.
        for item in self.items.select_related("plan"):
            item.send_slack_notification("cancelled")

    def uncancel(self):
        """Re-enable renewal for a subscription that was pending cancellation.

        Clears the cancelled flag and cancel_at date locally, and removes
        cancel_at_period_end on the Stripe subscription so it auto-renews.
        """
        customer = self.organization.customer()
        if not customer.stripe_payment_method_id:
            raise ValidationError(
                _(
                    "No payment method on file. "
                    "Please add a payment method before re-subscribing."
                )
            )
        if self.stripe_subscription:
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .uncancel(self.stripe_subscription)
            )
            if updated:
                self.cache_stripe_subscription_fields(updated)
        self.cancelled = False
        self.cancel_at = None
        self.save()

    def stripe_modify(self):
        """Push local state to Stripe for every item on this subscription."""
        if self.stripe_subscription:
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .modify(
                    self.subscription_id,
                    cancel_at_period_end=not self.auto_renew,
                    items=self.stripe_items(include_ids=True),
                    billing=(
                        "send_invoice"
                        if self.interval == "annual"
                        else "charge_automatically"
                    ),
                    metadata={"action": f"Subscription ({self.organization})"},
                    days_until_due=(30 if self.interval == "annual" else None),
                )
            )
            self.cancelled = False
            if updated:
                self.cache_stripe_subscription_fields(updated)
            if not self.auto_renew and self.current_period_end:
                self.cancel_at = self.current_period_end.date()
            else:
                self.cancel_at = None
            self.save()

    class Meta:
        ordering = ("organization", "interval")
        constraints = [
            # Every real Stripe subscription id is unique; any number of
            # comped subscriptions may leave it blank.
            models.UniqueConstraint(
                fields=["subscription_id"],
                condition=~models.Q(subscription_id=""),
                name="unique_stripe_subscription_id_when_set",
            ),
            # One subscription per organization per billing shape.  Anything
            # that would need a second one for the same shape should be an
            # item on the existing subscription instead.
            models.UniqueConstraint(
                fields=["organization", "interval", "collection_method"],
                name="unique_subscription_per_billing_shape",
            ),
        ]

    def __str__(self):
        return (
            f"{self.organization.name}: {self.get_interval_display()}, "
            f"{self.get_collection_method_display()}"
        )


class SubscriptionItem(models.Model):
    """One line on a Stripe subscription.

    The organization is reached through `subscription`, deliberately not
    duplicated here: a denormalized copy that has to agree with its parent is
    exactly the kind of drift this migration exists to remove.
    """

    objects = SubscriptionItemQuerySet.as_manager()

    plan = models.ForeignKey(
        verbose_name=_("plan"),
        to="organizations.Plan",
        on_delete=models.CASCADE,
        related_name="subscription_items",
    )

    subscription = models.ForeignKey(
        verbose_name=_("subscription"),
        to="organizations.Subscription",
        on_delete=models.CASCADE,
        related_name="items",
        blank=True,
        null=True,
        help_text=_("The Stripe subscription this is a line on"),
    )
    stripe_item_id = models.CharField(
        _("stripe item id"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "The subscription item ID on stripe.  Blank for items that never "
            "reach Stripe, which is every comped one."
        ),
    )

    quantity = models.PositiveIntegerField(
        _("quantity"),
        default=1,
        help_text=_(
            "Number of units of this plan's resources granted to the organization"
        ),
    )

    plan_price = models.ForeignKey(
        verbose_name=_("plan price"),
        to="organizations.PlanPrice",
        on_delete=models.PROTECT,
        related_name="subscription_items",
        blank=True,
        null=True,
        help_text=_(
            "The price this subscription is billed at.  Nullable until every "
            "subscription has been migrated off the legacy plan foreign key."
        ),
    )

    cancelled = models.BooleanField(
        _("cancelled"),
        default=False,
        help_text=_(
            "This line is scheduled to stop at the end of the current billing "
            "period.  It still bills and still grants access until then, "
            "mirroring how a cancelled subscription behaves."
        ),
    )
    cancel_at = models.DateField(
        _("cancel at"),
        null=True,
        blank=True,
        help_text=_(
            "When this line is dropped from the Stripe subscription.  Taken "
            "from the subscription's current period end, because every line "
            "on a subscription shares one billing period."
        ),
    )
    granted_reason = models.TextField(
        _("granted reason"),
        blank=True,
        default="",
        help_text=_(
            "Why this subscription received non-standard pricing (comped, or a "
            "partner coupon).  Blank for ordinary self-serve subscriptions."
        ),
    )
    granted_by = models.ForeignKey(
        verbose_name=_("granted by"),
        to="users.User",
        on_delete=models.PROTECT,
        related_name="granted_subscriptions",
        blank=True,
        null=True,
        help_text=_(
            "Staff user who authorized the non-standard pricing.  Blank for "
            "ordinary self-serve subscriptions."
        ),
    )

    class Meta:
        # One line per plan per subscription.  "An organization may not hold
        # the same plan twice" is now wider than a single subscription can
        # see, so add_subscription() enforces that part.
        unique_together = ("subscription", "plan")
        ordering = ("plan",)

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Free"
        return f"SubscriptionItem: {self.subscription.organization} to {plan_name}"

    @property
    def organization(self):
        """The owning organization, reached through the parent subscription.

        Read-only on purpose: the column lives on `Subscription` so a line can
        never disagree with the subscription it bills on.  Select or prefetch
        `subscription__organization` before touching this in a loop.
        """
        return self.subscription.organization

    def modify(self, plan):
        """Change which plan this line bills.

        Never use this to move between products - that is an add plus a
        remove, since the two subscriptions bill separately.
        """
        self.plan = plan
        self.save()
        self.subscription.stripe_modify()

    def cancel(self):
        """Stop billing this line at the end of the current period.

        The last line on a subscription cancels the whole subscription, which
        Stripe handles itself through cancel_at_period_end.  Stripe has no
        equivalent for a single line, so any other line is only flagged here
        and removed by `restore_organization` once `cancel_at` arrives.  Either
        way the customer keeps what they paid for until the period runs out.
        """
        if self.subscription.items.count() <= 1:
            self.subscription.cancel()
            return

        self.cancelled = True
        period_end = self.subscription.current_period_end
        self.cancel_at = period_end.date() if period_end else None
        self.save()
        self.send_slack_notification("cancelled")

    def uncancel(self):
        """Reverse a pending cancellation, so long as the line is still here."""
        self.cancelled = False
        self.cancel_at = None
        self.save()

    def remove_from_stripe(self):
        """Drop this line from the Stripe subscription and delete it locally.

        Proration is suppressed: the line has already been paid for through
        the end of the period, so the next invoice should simply omit it
        rather than issue a credit.
        """
        if self.subscription.stripe_subscription and self.stripe_item_id:
            get_payment_provider().get_subscription_service().modify(
                self.subscription.subscription_id,
                items=[{"id": self.stripe_item_id, "deleted": True}],
                proration_behavior="none",
            )
        self.delete()

    def notify_started(self):
        """Announce a newly added line.

        The Mailchimp journey fires only for the line that first grants the
        organization entitlement, so an org that already has it through
        another line is not enrolled twice.
        """
        organization = self.subscription.organization
        if self.plan_id and self.plan.entitlements.filter(slug="organization").exists():
            already_has_org_entitlement = (
                SubscriptionItem.objects.filter(
                    subscription__organization=organization,
                    plan__entitlements__slug="organization",
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if not already_has_org_entitlement:
                journey_key = (
                    "verified_premium_org"
                    if organization.verified_journalist
                    else "unverified_premium_org"
                )
                for user in organization.users.all():
                    mailchimp_journey(user.email, journey_key)

        self.send_slack_notification("started")

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

    PRODUCT_CHOICES = [
        ("muckrock", _("MuckRock")),
        ("documentcloud", _("DocumentCloud")),
        ("sunlight", _("Sunlight")),
        ("scoutpost", _("Scoutpost")),
    ]

    product = models.CharField(
        _("product"),
        max_length=20,
        choices=PRODUCT_CHOICES,
        blank=True,
        default="",
        help_text=_(
            "Which product this plan is marketed under, for grouping tiers on "
            "the plan page.  This is a display label, not a description of "
            "what the plan grants - most plans span more than one product "
            "(Sunlight tiers grant MuckRock and DocumentCloud entitlements but "
            "are still marketed as Sunlight).  Do NOT use this to decide "
            "whether a plan switch is an upgrade or an unrelated addition; "
            "compare the entitlement client sets instead.  Blank on legacy "
            "plans not yet mapped to a tier."
        ),
    )
    stripe_product_id = models.CharField(
        _("stripe product id"),
        max_length=255,
        blank=True,
        default="",
        help_text=_("The Product ID on stripe that this plan's Prices hang off"),
    )

    # DEPRECATED: minimum_users and price_per_user encode the per-user
    # resource-block pricing model, which is being replaced by flat-rate plans
    # plus quantity-based add-on packs.  Both are load-bearing until every
    # per-user subscriber has been decomposed into a base + pack subscription
    # (see the Stripe modernization plan), and are removed after that.  Do not
    # zero them out early - the decomposition reads them to compute pack
    # quantity.
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
            current_count = SubscriptionItem.objects.sunlight_active_count()
            return current_count < settings.MAX_SUNLIGHT_SUBSCRIPTIONS
        return True

    def cost(self, users):
        """Total monthly cost for a given number of resource blocks

        DEPRECATED: superseded by PlanPrice.amount plus the subscription's
        pack quantity.  Kept accurate deliberately - flattening it to
        base_price early would misreport the price of every per-user
        subscriber that has not been decomposed yet.  Retire this along with
        its call sites before dropping base_price.
        """
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

    def ensure_stripe_product(self):
        """Create this plan's Stripe Product if it does not have one.

        One Product per plan; its prices hang off it as Stripe Prices.  The
        ID is saved immediately rather than by the caller, because a Product
        that exists in Stripe but whose ID was never persisted is an orphan
        nothing can find again.

        Safe to call repeatedly, including after a failure part-way through:
        an existing Product for this plan is adopted rather than duplicated.
        Saving the ID immediately is not enough on its own, because
        ATOMIC_REQUESTS makes every admin request a transaction that can
        still roll that save back afterwards.

        Returns the Stripe Product ID.
        """
        if self.stripe_product_id:
            return self.stripe_product_id

        plan_service = get_payment_provider().get_plan_service()
        product = plan_service.find_product(self.slug)
        if product is None:
            product = plan_service.create_product(
                name=self.name, metadata={"squarelet_plan_slug": self.slug}
            )
        self.stripe_product_id = product.id
        self.save(update_fields=["stripe_product_id"])
        return product.id

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


class PlanPrice(models.Model):
    """A Stripe Price belonging to a Plan

    Monthly and annual variants of one plan are Prices under a single Stripe
    Product, replacing the legacy one-Stripe-Plan-per-Plan model.

    `interval` and `label` are orthogonal: a nonprofit on an annual plan has
    interval="annual" and label="nonprofit".

    An individually negotiated rate is a price of its own, identified by
    `code` rather than by a label.  Stripe has no negative coupon, so a rate
    *above* list cannot be expressed as a discount on one - and a rate below
    list is the same kind of thing, so both are handled the same way.
    Coupons are kept for time-limited promotions, where expiry and redemption
    limits are what is wanted.
    """

    # Recurring only.  A Stripe Price with no `recurring` block cannot be a
    # subscription item, and access here is granted exclusively through
    # subscription lines - so a one-time price would bill correctly and grant
    # nothing.  A genuine one-off purchase needs its own model, and the
    # requirements that come with it (expiry, refunds, whether it grants
    # entitlements at all) should shape that rather than being guessed now.
    # Plans that should bill once and stop use Plan.auto_renew instead.
    INTERVAL_CHOICES = [
        ("monthly", _("Monthly")),
        ("annual", _("Annual")),
    ]
    LABEL_CHOICES = [
        ("standard", _("Standard")),
        ("nonprofit", _("Nonprofit")),
        ("comped", _("Comped")),
    ]

    plan = models.ForeignKey(
        verbose_name=_("plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="prices",
        help_text=_("The plan this price belongs to"),
    )
    stripe_price_id = models.CharField(
        _("stripe price id"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "The Price ID on stripe.  Blank for comped prices: those never "
            "create a Stripe subscription, so they have no Stripe counterpart "
            "to point at.  Uniqueness is enforced only on non-blank values."
        ),
    )
    interval = models.CharField(
        _("interval"),
        max_length=20,
        choices=INTERVAL_CHOICES,
        help_text=_("How often this price is billed"),
    )
    label = models.CharField(
        _("label"),
        max_length=20,
        choices=LABEL_CHOICES,
        default="standard",
        help_text=_("Ongoing structural rate class this price represents"),
    )
    code = models.SlugField(
        _("code"),
        max_length=50,
        blank=True,
        default="",
        help_text=_(
            "Blank for list pricing - one such price per plan, interval and "
            "label.  Set to a short slug naming an individually negotiated "
            "deal (e.g. 'insideclimate'), which may sit above or below list: "
            "Stripe has no negative coupon, so a rate above list can only be "
            "expressed as a price of its own.  Coupons are for time-limited "
            "promotions."
        ),
    )
    amount = models.PositiveIntegerField(
        _("amount"),
        help_text=_(
            "Amount in cents, matching Charge.amount and Stripe's unit_amount.  "
            "Note the legacy Plan.base_price is in whole dollars - the two "
            "coexist until that field is removed."
        ),
    )
    currency = models.CharField(
        _("currency"),
        max_length=3,
        default="usd",
        help_text=_("ISO 4217 currency code"),
    )
    active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Whether new subscriptions use this price.  Stripe Prices are "
            "immutable, so changing what a tier costs means superseding this "
            "row rather than editing it: the old row stays, inactive, still "
            "pointing at the Stripe Price its existing subscribers are "
            "billed against."
        ),
    )

    class Meta:
        ordering = ("plan", "interval", "label", "code")
        constraints = [
            # Partial: every real Stripe Price ID must be unique, but any
            # number of comped prices may leave it blank.
            models.UniqueConstraint(
                fields=["stripe_price_id"],
                condition=~models.Q(stripe_price_id=""),
                name="unique_stripe_price_id_when_set",
            ),
            # One *active* price per variant, where a negotiated `code`
            # makes its own variant.  List pricing (code="") therefore keeps
            # exactly one active row per plan/interval/label, while any
            # number of negotiated deals coexist alongside it.  Superseded
            # rows accumulate freely so existing subscribers keep billing at
            # what they signed up for.
            models.UniqueConstraint(
                fields=["plan", "interval", "label", "code"],
                condition=models.Q(active=True),
                name="unique_active_plan_price",
            ),
        ]

    def __str__(self):
        parts = [self.get_interval_display(), self.get_label_display()]
        if self.code:
            parts.append(self.code)
        if not self.active:
            parts.append("superseded")
        return f"{self.plan.name} ({', '.join(parts)})"

    # The terms Stripe bakes into a Price and will not let you change.
    # `label` and `code` are local classification and stay editable.
    STRIPE_BOUND_FIELDS = ("amount", "currency", "interval")

    def clean(self):
        """Refuse edits that would make this row disagree with Stripe.

        A Stripe Price is immutable, so changing what this row says it costs
        would leave the UI quoting one figure while subscribers keep being
        billed another - the same silent divergence between display and
        Stripe that this project already has one live bug from.  Supersede
        instead: it retires this row and creates a replacement carrying the
        new terms.
        """
        super().clean()
        if not self.pk or not self.stripe_price_id:
            return

        original = (
            PlanPrice.objects.filter(pk=self.pk)
            .values(*self.STRIPE_BOUND_FIELDS)
            .first()
        )
        if original is None:
            return

        changed = [
            field
            for field in self.STRIPE_BOUND_FIELDS
            if original[field] != getattr(self, field)
        ]
        if changed:
            raise ValidationError(
                {
                    field: _(
                        "This price already exists on Stripe and cannot be "
                        "changed. Use supersede to retire it and create a "
                        "replacement at the new terms."
                    )
                    for field in changed
                }
            )

    @property
    def amount_dollars(self):
        return self.amount / 100.0

    @property
    def variant_key(self):
        """A stable identity for what this price *is*.

        Deliberately derived from the price's terms rather than from its
        primary key: if the transaction that created the row aborts after
        Stripe has already made the Price, the row - and its pk - are gone,
        but the terms someone retries with are identical.  That is what lets
        the retry find the orphaned Price instead of making another.
        """
        return ":".join(
            str(part)
            for part in (
                self.plan.slug,
                self.interval,
                self.label,
                self.code,
                self.amount,
                self.currency,
            )
        )

    def ensure_stripe_price(self):
        """Point this row at a Stripe Price, creating one only if needed.

        No-ops for comped prices - they cost nothing, never create a Stripe
        subscription, and so have no Stripe counterpart - and for rows that
        already have a Price.  Creates the plan's Product first if it does
        not have one yet.

        Safe to call repeatedly, including after a failure part-way through:
        an existing Price for these terms is adopted rather than duplicated.
        That matters because ATOMIC_REQUESTS wraps every admin request in a
        transaction, so any later error rolls the database back while
        leaving anything already created in Stripe untouched.

        Returns the Stripe Price ID, or None for a comped price.
        """
        if self.amount == 0:
            return None
        if self.stripe_price_id:
            return self.stripe_price_id

        product_id = self.plan.ensure_stripe_product()
        plan_service = get_payment_provider().get_plan_service()
        variant_key = self.variant_key

        price = plan_service.find_price(product_id, variant_key)
        if price is None:
            price = plan_service.create_price(
                product_id=product_id,
                unit_amount=self.amount,
                currency=self.currency,
                interval=self.interval,
                metadata={
                    "squarelet_plan_slug": self.plan.slug,
                    "label": self.label,
                    "squarelet_variant": variant_key,
                },
            )
        self.stripe_price_id = price.id
        self.save(update_fields=["stripe_price_id"])
        return price.id

    def supersede(self, amount):
        """Retire this price and return its replacement at a new amount.

        Stripe Prices cannot be edited, so a price change is a new Price.
        This row is marked inactive and keeps pointing at the Stripe Price
        its existing subscribers are billed against; the returned row is the
        one new subscriptions should use.

        Callers are responsible for moving subscribers over if that is
        wanted - superseding alone changes nobody's bill.
        """
        if not self.active:
            raise ValueError("Cannot supersede an already superseded price")

        # Only the database work is atomic.  Wrapping the Stripe call too
        # would mean a rollback could discard the local record of a Price
        # that Stripe has already made and cannot undo.
        with transaction.atomic():
            self.active = False
            self.save(update_fields=["active"])

            replacement = PlanPrice.objects.create(
                plan=self.plan,
                stripe_price_id="",
                interval=self.interval,
                label=self.label,
                # Carried over deliberately: superseding a negotiated rate
                # must produce a new rate for the same deal, not a list price.
                code=self.code,
                amount=amount,
                currency=self.currency,
            )

        # Idempotent, so a failure here is finished by calling it again -
        # which matters under ATOMIC_REQUESTS, where the caller's request is
        # itself a transaction that this cannot escape.
        replacement.ensure_stripe_price()
        return replacement


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

    receipt_pdf = models.FileField(
        _("receipt pdf"),
        upload_to="receipts/",
        storage=private_storage,
        null=True,
        blank=True,
    )

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

    @property
    def pdf_url(self):
        if self.receipt_pdf:
            return self.receipt_pdf.url
        return None


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
            rule_clauses.append(Q(subscriptions__items__isnull=False))

        if rule_clauses:
            rule_q = rule_clauses[0]
            for clause in rule_clauses[1:]:
                rule_q &= clause
            return eligible.filter(explicit_q | rule_q).distinct()
        return eligible.filter(explicit_q)


class ReceiptEmail(models.Model):
    """The billing email address for an organization"""

    organization = models.OneToOneField(
        verbose_name=_("organization"),
        to="organizations.Organization",
        related_name="receipt_email",
        on_delete=models.CASCADE,
        help_text=_("The organization this billing email corresponds to"),
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

    def __str__(self):
        return f"Receipt Email: <{self.email}>"


class PaymentMethod(models.Model):
    """A cached payment method for a Customer."""

    class MethodType(models.TextChoices):
        CARD = "card", "Card"
        BANK_ACCOUNT = "bank_account", "Bank Account"
        OTHER = "other", "Other"

    customer = models.ForeignKey(
        "organizations.Customer",
        on_delete=models.CASCADE,
        related_name="payment_methods",
    )
    method_type = models.CharField(
        max_length=20,
        choices=MethodType.choices,
        default=MethodType.CARD,
    )
    brand = models.CharField(max_length=64, blank=True, default="")
    last4 = models.CharField(max_length=4, blank=True, default="")
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    stripe_id = models.CharField(max_length=255, blank=True, default="")
    is_default = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["customer"],
                condition=models.Q(is_default=True),
                name="unique_default_per_customer",
            ),
        ]

    def __str__(self):
        return f"{self.get_method_type_display()}" f" {self.brand} x{self.last4}"

    @property
    def display(self):
        if self.brand and self.last4:
            return f"{self.brand}: x{self.last4}"
        return ""
