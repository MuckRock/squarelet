# Django
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime
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
from squarelet.organizations.payments.exceptions import SubscriptionError
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


# Resource keys that describe a level or threshold rather than a quantity, and so
# should not be added together when aggregating entitlements.
TIER_RESOURCES = frozenset({"feature_level", "minimum_users"})


def sum_resources(resources):
    """Aggregate an iterable of entitlement ``resources`` dicts into one dict.

    Quantities are summed, so a subject holding two entitlements that each grant
    50 requests gets 100. Flags are OR'd -- granted by any entitlement means
    granted. Keys in :data:`TIER_RESOURCES` take the highest value instead of
    summing. Anything else keeps the first value seen.
    """
    total = {}
    for resource in resources:
        for key, value in (resource or {}).items():
            if key not in total:
                total[key] = value
            elif isinstance(total[key], bool) or isinstance(value, bool):
                total[key] = bool(total[key]) or bool(value)
            elif not isinstance(total[key], (int, float)) or not isinstance(
                value, (int, float)
            ):
                continue  # incompatible types -- keep the first value
            elif key in TIER_RESOURCES:
                total[key] = max(total[key], value)
            else:
                # it's safe to sum these values
                total[key] = total[key] + value
    return total


def format_benefits(benefits, resources):
    """Render benefit strings, filling in quantities from ``resources``.

    Benefit copy refers to resources by name, e.g.
    ``"{base_requests} free public records requests each month"``, which lets a
    single benefit string express the aggregate of several entitlements. Format
    specs work too, e.g. ``"{pages:,} pages"``. A benefit whose placeholders
    can't be resolved is shown as authored rather than dropped.
    """
    formatted = []
    for benefit in benefits:
        try:
            formatted.append(benefit.format(**resources))
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Could not format benefit %r with resources %r: %s",
                benefit,
                resources,
                exc,
                exc_info=sys.exc_info(),
            )
            formatted.append(benefit)
    return formatted


def consolidate_plan_benefits(plans):
    """Consolidate the benefits of several ``plans`` into one display list.

    Benefit copy is deduped unformatted, then formatted once against the summed
    resources of every plan, so two plans that each grant 50 requests produce a
    single benefit reading 100 rather than two identical entries. Used to render
    one benefits list for a subject's whole set of plans instead of one list per
    plan.
    """
    templates = []
    resources = []
    for plan in plans:
        for benefit in plan.get_benefit_templates():
            if benefit not in templates:
                templates.append(benefit)
        resources.append(plan.get_resources())
    return format_benefits(templates, sum_resources(resources))


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


def _stripe_price_id(stripe_item):
    """The Price id on a Stripe subscription item, old field name or new.

    Subscript access throughout: a StripeObject refuses `.get`, the way it
    shadows `.items` - "'get' is a dict method, but a SubscriptionItem is
    not a dict".  It is dict-*like*, not a dict, and the difference only
    shows against the real API.
    """
    for key in ("price", "plan"):
        try:
            price = stripe_item[key]
        except (KeyError, TypeError):
            continue
        if not price:
            continue
        try:
            return price["id"]
        except (KeyError, TypeError):
            return None
    return None


class Cancellable:
    """The `cancelled`/`cancel_at` pair, shared by a subscription and its lines.

    Both models carry the pair and both mean the same thing by it: this
    stops at `cancel_at`, and until then it still bills and still grants
    access.  The nightly sweep in `tasks` acts on `cancelled=True` with a
    `cancel_at` that has arrived *or is null*, so half of the pair on its
    own - the flag set with no date - reads as "delete this tonight".
    Setting the fields by hand is what produced that, more than once, so
    they are written only here.

    Neither method saves.  Every caller is already writing other fields in
    the same query, and some of them name their fields explicitly;
    `CANCELLATION_FIELDS` is for those.
    """

    CANCELLATION_FIELDS = ("cancelled", "cancel_at")

    def mark_cancelled(self, period_end):
        """Stop at the end of the period closing at `period_end`.

        No period end means nothing is paid for beyond now, which is the
        state a comped or never-started subscription is in: the sweep reads
        the null date as due immediately.
        """
        self.cancelled = True
        # Local, the way `next_date` reads the same field.  Straight
        # `.date()` agrees only while the value is the one just cached from
        # Stripe, which is built local-aware; read back from the database it
        # is UTC, and a period ending after 20:00 local lands on the next
        # day.  The card then says it ends the day after it renews, and the
        # sweep keeps the entitlements an extra day.
        self.cancel_at = localtime(period_end).date() if period_end else None

    def clear_cancellation(self):
        """No longer stopping - back to renewing normally."""
        self.cancelled = False
        self.cancel_at = None

    def inherit_cancellation_from(self, subscription):
        """Take the subscription's ending as this line's own.

        It stops when the subscription does, on the subscription's date -
        deriving that date again from the period end could disagree with
        what the parent actually holds.

        Flagged as inherited, so that reviving the subscription revives this
        line too - unlike one the customer cancelled on its own.

        Not every line joining a cancelling subscription ends up here.  A
        paid, renewing one is a reason to carry on instead, and lifts the
        cancellation through `Subscription.keep_renewing_for`; this is what
        happens to the rest - a free line or a one-off purchase, neither of
        which Stripe is billing next period anyway.
        """
        self.cancelled = subscription.cancelled
        self.cancel_at = subscription.cancel_at
        self.cancelled_with_subscription = subscription.cancelled


class Subscription(Cancellable, models.Model):
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

    # What `cache_stripe_subscription_fields` writes.  Named because two
    # callers save by explicit field list, and a field added to the method
    # but not to their lists is simply never persisted - which has already
    # happened once, to `stripe_status`.
    STRIPE_CACHED_FIELDS = (
        "stripe_status",
        "collection_method",
        "current_period_end",
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
        return all(
            item.is_free for item in self.items.select_related("plan", "plan_price")
        )

    @property
    def auto_renew(self):
        """Does the subscription itself renew?

        It does as long as one line still wants to.  A single non-renewing
        plan must not drag the renewing lines down with it - that line stops
        on its own, through `cancelled`/`cancel_at`, the same way a line the
        customer cancelled does.  Only when every line has stopped does the
        subscription end.
        """
        items = list(self.items.all())
        if not items:
            return True
        return any(item.plan.auto_renew for item in items)

    @property
    def next_date(self):
        """The date this subscription next renews, or ends if cancelled.

        Read from the cached `current_period_end` rather than from Stripe:
        the billing pages render one row per line, and asking Stripe per row
        turned a page view into a fan of API calls.  The webhook keeps this
        field current, and `audit_subscriptions` is what verifies that.
        """
        if not self.current_period_end:
            return None
        return localtime(self.current_period_end).date()

    def stripe_items(self, include_ids=False):
        """Stripe line specs for every item on this subscription.

        Pass include_ids when modifying an existing subscription: Stripe needs
        each line's own id to update it in place rather than replace it.
        """
        specs = []
        for item in self.items.select_related("plan", "plan_price"):
            if item.is_free:
                # Nothing for Stripe to bill.  A comped or free line has no
                # Stripe counterpart at all, so naming it would reference an
                # object that does not exist and fail the whole call -
                # including the paid lines alongside it.
                continue
            spec = {"plan": item.stripe_price_id, "quantity": item.quantity}
            if include_ids and item.stripe_item_id:
                spec["id"] = item.stripe_item_id
            specs.append(spec)
        return specs

    def sync_stripe_item_ids(self, stripe_sub):
        """Record the Stripe id of each line, matching them up by Price.

        `stripe_items(include_ids=True)` omits the id it does not have, and a
        line spec with no id is how you ask Stripe to *add* a line rather
        than update one.  So a line with a blank `stripe_item_id` is either
        rejected - "an existing Subscription Item is already using that
        Price" - or, where Stripe accepts it, silently duplicated and billed
        twice.

        Two ways a line ends up in that state.  Anything predating the
        subscription/item split: the column arrived empty and the data
        migration had nothing to fill it from, the old schema having had one
        Stripe subscription per row and no per-line id at all.  And any line
        Stripe created for us since, which is what the backfill relies on -
        it is deliberately re-runnable, with no "done" marker, so a second
        pass over an already-migrated subscriber has to be a no-op rather
        than a second pack line.

        Matching on the Price is what makes the write-back safe: a
        subscription cannot hold the same Price twice, so the correspondence
        is one-to-one.

        Note `stripe_sub["items"]` rather than `stripe_sub.items` - a
        StripeObject is dict-like, and attribute access reaches the dict
        method instead of the field.
        """
        try:
            data = stripe_sub["items"]["data"]
        except (KeyError, TypeError):
            return

        by_price = {}
        for stripe_item in data:
            price_id = _stripe_price_id(stripe_item)
            if price_id:
                by_price[price_id] = stripe_item["id"]

        for item in self.items.select_related("plan", "plan_price"):
            if item.is_free:
                continue
            # Whatever `stripe_items` sends as the price is what Stripe
            # echoes back, so the two have to read the same field.
            item_id = by_price.get(item.stripe_price_id)
            if item_id and item_id != item.stripe_item_id:
                item.stripe_item_id = item_id
                item.save(update_fields=["stripe_item_id"])

    def remember_stripe_subscription(self, stripe_sub):
        """Seed or clear the `stripe_subscription` cache.

        It is a `cached_property`, and `start()` consults it to decide
        whether there is already a subscription - necessarily before it has
        an id to consult it with.  So it computes None and caches that, and
        every later read on the same instance sees None however true it has
        since stopped being: `stripe_modify` quietly does nothing, and the
        free branch of `sync_to_stripe` tries to delete None.

        Seeding it with the object we already hold also saves the round trip
        that reading it back would cost.
        """
        self.__dict__["stripe_subscription"] = stripe_sub

    def cache_stripe_subscription_fields(self, stripe_sub):
        """Cache subscription status and period end from a Stripe subscription.

        A payload carrying no period end is not saying the subscription has
        none - webhooks omit `items` for a bare cancel_at_period_end toggle,
        which is the very event a cancellation fires.  Overwriting with None
        there discarded the date `cancel()` had just worked out, and
        `mark_cancelled` then wrote a cancellation with no date - which the
        nightly sweep reads as due immediately.  The customer lost their
        entitlements the same night while Stripe billed them to period end.
        """
        self.stripe_status = stripe_sub.status or ""
        # Cached, not computed.  How Stripe collects is Stripe's fact, and
        # the local copy started as a guess: `0084` infers it from
        # `plan.annual`, while the runtime keys it on the payment method, so
        # an annual subscriber paying by card was migrated as `send_invoice`
        # and no longer matched the `get_or_create` that looks for their
        # subscription - giving them a second one, and a second invoice.
        # Reading it back from Stripe heals that on any interaction.
        try:
            collection_method = stripe_sub["collection_method"]
        except (KeyError, TypeError):
            collection_method = None
        if collection_method:
            self.collection_method = collection_method
        ts = (
            get_payment_provider()
            .get_subscription_service()
            .get_current_period_end(stripe_sub)
        )
        if ts:
            self.current_period_end = datetime.fromtimestamp(
                ts, tz=get_current_timezone()
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
        self.remember_stripe_subscription(stripe_subscription)
        self.cache_stripe_subscription_fields(stripe_subscription)
        if not self.auto_renew and self.current_period_end:
            # Stripe was told cancel_at_period_end just above, so the local
            # record says the same thing.  `stripe_modify` and the
            # subscription webhook already agree on this; start used to set
            # the date and leave the flag false, which every reader of the
            # pair takes to mean "renews".
            self.mark_cancelled(self.current_period_end)
        # Save before creating the invoice
        self.save()

        # Record the id Stripe gave each line while we are holding the object
        # that carries them.  Without this every subscription starts life
        # unidentified - the state the backfill command exists to repair -
        # so the audit reports each line as missing on Stripe and the next
        # modify asks Stripe to add a line it already has.
        self.sync_stripe_item_ids(stripe_subscription)

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
        # A settled invoice needs no authenticating, and Stripe hands back a
        # confirmation secret either way - so the secret's presence never
        # meant action was required.  Checked here rather than by the
        # callers, who were each guessing at it from the subscription's
        # status instead.
        if fresh_invoice.status == "paid":
            return

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

    def settle_added_line(self, stripe_subscription):
        """Finish the charge Stripe made for a line just added.

        A card payer is invoiced for the proration then and there (see
        `proration_behavior`), so it is a charge like any other: the card
        may have to authenticate it, and it produces an invoice worth
        keeping.  `start` does both for a subscription it creates; the path
        that adds to one already live did neither, so a card needing SCA
        was never challenged - the view reported success, the charge sat
        unauthenticated, and no local Invoice row was written for money
        that had been taken.

        Both halves are no-ops for an invoiced organization, whose change
        rides on the next scheduled invoice: there is no new invoice to
        record and nothing to authenticate, so this re-reads the invoice it
        already knows about and finds nothing to do.
        """
        self._check_3ds_action_required(stripe_subscription)
        self._sync_latest_invoice(stripe_subscription)

    def other_paid_items(self, item):
        """Every paid line on this subscription except `item`.

        Stripe holds only the paid ones: `stripe_items` drops free lines
        before describing the subscription, because naming a Plan with no
        Stripe counterpart fails the whole call.  So any question about
        what Stripe will still have afterwards is a question about these,
        and counting local rows answers a different one - the two disagree
        exactly when a subscription mixes free and paid.

        Callers ask two different things of the result, and the difference
        matters: whether anything is still *renewing* (so the subscription
        should carry on) is not the same as whether anything is still *on
        Stripe* (so an item can be removed without leaving none).  A line
        flagged to stop next month is not renewing, but Stripe is still
        billing it today.
        """
        return [
            sibling
            for sibling in self.items.select_related("plan")
            if sibling.pk != item.pk and not sibling.is_free
        ]

    def push_cancellation_to_items(self):
        """Give every line this subscription's own cancellation state.

        Lines mirror their subscription because they bill on one Stripe
        subscription and therefore stop together.  The UI lists lines, not
        subscriptions, so a line has to be able to say it is going away
        without consulting its parent.  Copied from `self` rather than
        restated, so the two cannot be written to disagree.
        """
        if self.cancelled:
            # A line already ending keeps its own date and its own reason.
            self.items.exclude(cancelled=True).update(
                cancelled=True,
                cancel_at=self.cancel_at,
                cancelled_with_subscription=True,
            )
        else:
            # Only the lines this subscription ended.  Stripe knows nothing
            # about a line the customer cancelled by itself, so neither a
            # reversal here nor anything arriving from Stripe is an answer
            # about those.
            self.items.filter(cancelled_with_subscription=True).update(
                cancelled=False, cancel_at=None, cancelled_with_subscription=False
            )

    def keep_renewing_for(self, item):
        """Stop ending, because a line is arriving that means to stay.

        `cancel_at_period_end` belongs to the subscription, so a line added
        to one that is ending would be deleted along with it when the period
        runs out - the customer buys a plan and silently loses it.  Lifting
        the cancellation is the only way to keep the new line, and it must
        not also revive what the customer asked to end.

        So the lines that were stopping only because the subscription was
        become lines stopping in their own right: same date, same flag, but
        no longer waiting on the parent.  `uncancel` and the Stripe webhook
        revive only `cancelled_with_subscription` lines, so they now leave
        these alone, and `restore_organization` drops each one when its own
        `cancel_at` arrives - legally, because `item` is a paid sibling that
        outlives them.

        Left to the caller to keep this to a paid, renewing line.  A free
        one is never sent to Stripe, so it cannot hold up a subscription
        Stripe is renewing; a one-off is flagged to stop the moment it is
        bought.  Either would leave Stripe renewing a subscription whose
        only surviving paid line is cancelled - the state `restore_organization`
        can do nothing with and logs an error about.
        """
        self.items.exclude(pk=item.pk).filter(cancelled_with_subscription=True).update(
            cancelled_with_subscription=False
        )
        self.clear_cancellation()
        self.save(update_fields=self.CANCELLATION_FIELDS)

    def cancel(self):
        if self.stripe_subscription:
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .cancel_at_period_end(self.stripe_subscription)
            )
            if updated:
                self.cache_stripe_subscription_fields(updated)
        self.mark_cancelled(self.current_period_end)
        self.save()
        self.push_cancellation_to_items()

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
        self.clear_cancellation()
        self.save()
        self.push_cancellation_to_items()

    def sync_to_stripe(self, payment_method="card"):
        """Make Stripe match this subscription, from whatever state it is in.

        Returns the Stripe subscription only when it created one; None
        otherwise.  The three transitions a plan change can cause, in one
        place:

        - it has become entirely free, so the Stripe subscription is deleted
          and the customer stops being charged;
        - it has become paid and had no Stripe subscription, so one is
          created;
        - it was paid and stays paid, so the existing one is updated.

        `stripe_modify` alone covers only the third.  It no-ops without a
        Stripe subscription, which is exactly the state an organization on a
        free plan is in - so an upgrade would have granted paid access and
        never billed for it, and a downgrade would have left the customer
        being charged for a free plan.
        """
        if self.free:
            if self.subscription_id:
                # Stripe may not have it any more: `retrieve` answers None
                # for a subscription cancelled in the dashboard, and
                # deleting None raises - which left the local record still
                # naming it, so the downgrade could never complete and every
                # retry failed the same way.  Gone from Stripe is the state
                # this branch is trying to reach, so take it.
                if self.stripe_subscription is not None:
                    get_payment_provider().get_subscription_service().delete(
                        self.stripe_subscription
                    )
                self.subscription_id = ""
                self.remember_stripe_subscription(None)
                # The lines' ids named items on the subscription just
                # deleted.  Left behind they would be sent to whatever
                # subscription is started next, which has never heard of
                # them - "No such subscription_item", and a line that cannot
                # be removed.
                self.items.update(stripe_item_id="")
                # Nothing is pending once the Stripe subscription is gone.
                # This used to clear the date and leave the flag, which is
                # the pair's worst half-state: the sweep reads it as due
                # immediately and deletes the subscription the customer has
                # just downgraded onto, every line with it.
                self.clear_cancellation()
                self.save(update_fields=["subscription_id", *self.CANCELLATION_FIELDS])
                self.push_cancellation_to_items()
            return None
        if not self.subscription_id:
            return self.start(payment_method=payment_method)
        self.stripe_modify()
        # Deliberately not `self.stripe_subscription` - that property fetches
        # from Stripe, and no caller wants the object badly enough to pay for
        # a round trip on every plan change.
        return None

    @property
    def proration_behavior(self):
        """How Stripe should settle a mid-period change to these lines.

        A card payer gets the invoice at the moment they act.  Stripe's
        default is `create_prorations`, which writes the proration onto the
        *upcoming* invoice and raises nothing now - so adding a plan
        appeared to cost nothing until the next cycle, and there was no
        invoice for it to look at.  It also left the SCA check in
        `settle_added_line` guarding a charge that was never made.

        An invoiced organization is left on the default deliberately.
        `always_invoice` would email them a separate invoice with its own
        due date part-way through a term they have already been billed for;
        folding the change into the next scheduled invoice is what their
        billing arrangement is for.
        """
        if self.collection_method == "send_invoice":
            return "create_prorations"
        return "always_invoice"

    def stripe_modify(self, proration_behavior=None):
        """Push local state to Stripe for every item on this subscription.

        `proration_behavior` overrides the answer above for one call.  Pass
        "none" for a change that is not meant to alter what the customer
        pays, such as moving a line onto the Price that represents the same
        money it was already billing.
        """
        if self.stripe_subscription:
            # Learn any missing line ids before describing the lines, not
            # after.  A line with no `stripe_item_id` is sent with no id, and
            # a spec with no id asks Stripe to *add* a line - which it then
            # refuses, because that Price is already on the subscription.
            # Every line that predates the subscription/item split is in that
            # state: the column was added empty and nothing populated it, so
            # the first modify of any existing subscription failed.
            #
            # Free either way: `stripe_subscription` is a cached_property
            # already fetched by the check above.
            self.sync_stripe_item_ids(self.stripe_subscription)
            updated = (
                get_payment_provider()
                .get_subscription_service()
                .modify(
                    self.subscription_id,
                    # A pending cancellation survives an unrelated change.
                    # Sending `not auto_renew` alone would reverse it on
                    # Stripe the next time any line was added or modified.
                    cancel_at_period_end=self.cancelled or not self.auto_renew,
                    items=self.stripe_items(include_ids=True),
                    # The subscription's own collection method, not a guess
                    # from its interval.  Deriving it from `annual` pushed
                    # `send_invoice` at every annual subscriber, so adding a
                    # plan silently stopped auto-charging the ones paying by
                    # card - while the local row went on saying they were.
                    billing=self.collection_method,
                    metadata={"action": f"Subscription ({self.organization})"},
                    days_until_due=(
                        30 if self.collection_method == "send_invoice" else None
                    ),
                    proration_behavior=(
                        self.proration_behavior
                        if proration_behavior is None
                        else proration_behavior
                    ),
                )
            )
            if updated:
                self.cache_stripe_subscription_fields(updated)
                self.sync_stripe_item_ids(updated)
            # Cancellation is owned by cancel(), uncancel() and the Stripe
            # webhook.  This method used to clear it on every call, which
            # silently revived a subscription whenever an unrelated line was
            # touched.
            if self.cancelled or not self.auto_renew:
                self.mark_cancelled(self.current_period_end)
            self.save()
            return updated
        return None

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


class SubscriptionItem(Cancellable, models.Model):
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
        help_text=_(
            "The Stripe subscription this is a line on.  Required: a line "
            "reaches its organization, its billing period and its "
            "cancellation through here, so one without a parent has no "
            "organization and cannot be rendered, billed or cancelled."
        ),
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
    cancelled_with_subscription = models.BooleanField(
        _("cancelled with subscription"),
        default=False,
        help_text=_(
            "This line is ending only because its subscription is, rather "
            "than because anyone cancelled the line itself.  Reviving the "
            "subscription revives these and leaves the rest alone - without "
            "which a customer who cancelled two plans and then resubscribed "
            "to a third got all three back."
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
    def is_free(self):
        """Whether this line costs anything.

        Reads the price once the line has one, and falls back to the plan
        while `plan_price` can still be null - which it is for every
        subscriber the backfill deliberately skipped, and for every signup
        until the purchase flow starts recording a price.
        """
        if self.plan_price_id:
            return self.plan_price.amount == 0
        return self.plan is None or self.plan.free

    @property
    def is_nonprofit(self):
        """Whether this line is billing at a nonprofit rate.

        A fact about the customer rather than about the tier, so it has to
        survive a move between tiers.  Self-reported and on the honour
        system, the way the checkbox that sets it is.
        """
        return bool(self.plan_price_id and self.plan_price.label == "nonprofit")

    @property
    def stripe_price_id(self):
        """The Stripe object this line bills against.

        Prefers the `PlanPrice`'s Stripe Price.  Falls back to the plan's
        legacy id in two cases: while `plan_price` is still null, and when
        a price exists but has no Stripe Price yet - a partial state
        `consolidate_stripe_products` can leave and completes on a re-run.
        Falling back means the line keeps billing exactly as it did before,
        which is the safe reading of "not ready yet".

        A free line has no Stripe counterpart at all; `stripe_items` drops
        those before asking.
        """
        if self.plan_price_id and self.plan_price.stripe_price_id:
            return self.plan_price.stripe_price_id
        return self.plan.stripe_id

    @property
    def organization(self):
        """The owning organization, reached through the parent subscription.

        Read-only on purpose: the column lives on `Subscription` so a line can
        never disagree with the subscription it bills on.  Select or prefetch
        `subscription__organization` before touching this in a loop.
        """
        return self.subscription.organization

    @property
    def next_date(self):
        """When this line next renews, or ends if it is cancelled.

        Delegates to the subscription: every line on one shares a billing
        period, so the date is a fact about the parent.  Exposed here
        because the UI lists lines, and a template reaching for
        `current_period_end` on a line gets an empty string rather than an
        error - the renewal date simply stopped rendering when the field
        moved.
        """
        return self.subscription.next_date

    def modify(self, plan):
        """Change which plan this line bills.

        Never use this to move between products - that is an add plus a
        remove, since the two subscriptions bill separately.  A change of
        billing interval is the same thing and is refused here: Stripe will
        not carry a monthly and an annual price on one subscription, so the
        line has to move to the organization's subscription for the other
        interval, which is a remove and an add rather than an edit.  Left
        unchecked it silently pushed an annual price at a monthly
        subscription and Stripe rejected the whole call.

        Goes through `sync_to_stripe` rather than `stripe_modify`, because
        changing a line's plan can change whether the subscription bills at
        all: a free line becoming paid needs a Stripe subscription created,
        and the last paid line becoming free needs one deleted.

        Re-resolves the price, because the price is what the line bills
        against now.  Moving the plan and leaving `plan_price` behind kept
        the line on the old tier's Stripe Price - the customer would have
        been moved on paper and charged the old amount - and `is_free`
        would have answered about the tier they left.

        A line already on a nonprofit price stays on one: the label is a
        fact about the customer, not about the tier they are moving to.
        """
        # Identify this line on Stripe *before* changing the plan, because
        # the plan is what identifies it: `sync_stripe_item_ids` matches on
        # the Price, so once the local plan has moved on it matches nothing
        # and the line is described to Stripe with no id - which asks Stripe
        # to add a line rather than update one, leaving the customer billed
        # for the plan they left as well as the one they chose.
        # The billing shape follows the resolved price, not `plan.annual` -
        # the same reason `start` does it that way, since the row handed in
        # is not always the row that ends up being billed.
        canonical_plan, plan_price = SubscriptionItem.objects.resolve_purchase(
            plan, nonprofit=self.is_nonprofit
        )
        interval = (
            plan_price.interval
            if plan_price
            else "annual" if plan.annual else "monthly"
        )
        if interval != self.subscription.interval:
            raise SubscriptionError(
                f"Cannot change {self.plan} to {plan} in place: it bills "
                f"{interval} and this subscription bills "
                f"{self.subscription.interval}.  Remove the line and add the "
                f"new plan, which puts it on the right subscription."
            )

        stripe_sub = self.subscription.stripe_subscription
        if stripe_sub is not None:
            self.subscription.sync_stripe_item_ids(stripe_sub)
            # It wrote straight to the rows, so this instance is stale.
            self.refresh_from_db()

        # A subscription ending because *nothing on it renews* is ending for
        # a reason made of plans, and this method is changing one.  Anything
        # else - a customer cancelling, Stripe reporting one - is a decision
        # that survives a plan change; reversing those is `uncancel`'s job.
        ending_only_because_nothing_renews = (
            self.subscription.cancelled and not self.subscription.auto_renew
        )

        self.plan = canonical_plan
        self.plan_price = plan_price
        self.save()

        if ending_only_because_nothing_renews and self.subscription.auto_renew:
            # Something renews now, so the reason is gone.  Left in place it
            # would be re-sent to Stripe as cancel_at_period_end, and the
            # plan the customer has just bought would be deleted at the end
            # of the period they bought it for.
            self.subscription.clear_cancellation()
            self.subscription.save()
            self.subscription.push_cancellation_to_items()
            self.refresh_from_db()

        # A pending cancellation belonged to the plan being replaced.  Keeping
        # it would drop the line the customer has just chosen, on the old
        # plan's date - so re-derive it from the new plan, the way `start`
        # does.  Not while the subscription itself is ending: the line goes
        # with it, and saying otherwise would advertise a renewal that is not
        # coming.
        if not self.subscription.cancelled:
            if plan.auto_renew:
                self.clear_cancellation()
            else:
                self.mark_cancelled(self.subscription.current_period_end)
            self.save(
                update_fields=[
                    *self.CANCELLATION_FIELDS,
                    "cancelled_with_subscription",
                ]
            )
        self.subscription.sync_to_stripe()

    def cancel(self):
        """Stop billing this line at the end of the current period.

        The last *active* line cancels the whole subscription, which Stripe
        handles itself through cancel_at_period_end.  Stripe has no
        equivalent for a single line, so any other line is only flagged here
        and removed by `restore_organization` once `cancel_at` arrives.  Either
        way the customer keeps what they paid for until the period runs out.

        Counting matters, and it has to count the right lines.  Cancelling
        two lines one at a time must still cancel the subscription on the
        second call, or the sweep would later try to delete the
        subscription's only remaining item, which Stripe rejects.  And the
        lines that count are the paid ones: a free sibling keeps no
        subscription alive, so counting it made cancelling the only paid
        line look like an ordinary per-line cancellation and Stripe was
        never told to stop.

        A free line never reaches Stripe at all, so cancelling one is
        always the local, per-line case.
        """
        if not self.is_free and not any(
            sibling
            for sibling in self.subscription.other_paid_items(self)
            if not sibling.cancelled
        ):
            # Nothing paid would still be renewing, so the subscription is
            # ending whatever this line says - and only cancelling it as a
            # whole tells Stripe so.
            self.subscription.cancel()
            return

        self.mark_cancelled(self.subscription.current_period_end)
        self.save()
        self.send_slack_notification("cancelled")

    def uncancel(self):
        """Reverse a pending cancellation, so long as the line is still here.

        If the whole subscription is cancelled - which is what cancelling the
        last active line does - reviving any line revives the subscription,
        and with it the lines that were only ending because it was.

        A plan that bills once and stops is refused.  Such a line is flagged
        to end the moment it is bought - that is what "bills once" means - so
        it reads as cancelled on the billing page from the outset, beside a
        Resubscribe button it was never meant to have.  Pressing it would
        clear the flag, and because a subscription renews if *any* line does,
        the one-time purchase would then be charged every period with nothing
        to sweep it.
        """
        if not self.plan.auto_renew:
            raise SubscriptionError(
                f"{self.plan} is a one-time purchase and cannot be resumed.  "
                f"Buy it again to get another period."
            )

        if self.subscription.cancelled:
            self.subscription.uncancel()
            self.refresh_from_db()
            return

        self.clear_cancellation()
        self.save()

    def remove_from_stripe(self):
        """Drop this line from the Stripe subscription and delete it locally.

        Proration is suppressed: the line has already been paid for through
        the end of the period, so the next invoice should simply omit it
        rather than issue a credit.

        Identifies the line first.  `stripe_item_id` is empty on everything
        predating the subscription/item split, and this is what the nightly
        sweep uses to enforce a per-line cancellation - so without that step
        the row was deleted locally while Stripe carried on billing it, and
        the id that could have found it again went with the row.
        """
        stripe_sub = self.subscription.stripe_subscription
        if stripe_sub is not None:
            # Unconditionally, not only when the id is missing: an id that
            # is merely *wrong* is worse than one that is absent, because
            # Stripe rejects the whole call rather than the line.
            self.subscription.sync_stripe_item_ids(stripe_sub)
            # It wrote straight to the rows, so this instance is stale.
            self.refresh_from_db()

        if stripe_sub is not None and self.stripe_item_id:
            get_payment_provider().get_subscription_service().modify(
                self.subscription.subscription_id,
                items=[{"id": self.stripe_item_id, "deleted": True}],
                proration_behavior="none",
            )
        elif not self.is_free:
            # A paid line we cannot find on Stripe.  Deleting the row is
            # still right - it is what the customer asked for - but say so,
            # because the charge may outlive the record of what it was for.
            logger.error(
                "[SUBSCRIPTION-ITEM] Removing paid line %s (%s) for %s with "
                "no Stripe item to remove; check subscription %s for a "
                "charge that should have stopped.",
                self.pk,
                self.plan,
                self.subscription.organization,
                self.subscription.subscription_id or "(none)",
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

    def get_resources(self):
        """The resources this plan grants, aggregated across its entitlements."""
        return sum_resources(
            entitlement.resources
            for entitlement in self.entitlements.all()  # reuses any prefetch
        )

    def get_benefit_templates(self):
        """Effective benefit copy for display, before quantities are filled in.

        If any of this plan's entitlements define benefits, the deduplicated,
        order-preserving union of those overrides ``self.benefits``. Otherwise
        fall back to ``self.benefits``. This supports migrating benefit copy
        from plans onto entitlements one plan at a time.

        Callers that combine several plans should dedupe these templates and
        format them once against the plans' summed resources; everyone else
        wants :meth:`get_benefits`.
        """
        entitlement_benefits = []
        for entitlement in self.entitlements.all():  # reuses any prefetch
            for benefit in entitlement.benefits or []:
                if benefit not in entitlement_benefits:
                    entitlement_benefits.append(benefit)
        return entitlement_benefits or self.benefits

    def get_benefits(self):
        """Effective benefits for display, with resource quantities filled in."""
        return format_benefits(self.get_benefit_templates(), self.get_resources())

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
    benefits = models.JSONField(
        _("benefits"),
        default=list,
        blank=True,
        help_text=_(
            "Plain-language benefits granted by this entitlement. Refer to "
            "quantities by resource name instead of hard-coding them, e.g. "
            '"{base_requests} free requests each month", so that quantities from '
            "several entitlements can be summed into one benefit. When any of a "
            "plan's entitlements define benefits, they override the plan's own "
            "benefits list for display."
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
