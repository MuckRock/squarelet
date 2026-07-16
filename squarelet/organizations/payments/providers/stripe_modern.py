"""
Modern Stripe provider targeting current API versions.

Implements the same abstract interfaces as the legacy provider but uses
current Stripe API conventions. Translations from legacy parameter names
to current ones are handled here so call sites remain unchanged.

API version history tracked in this file:
  2019-10-17 - `billing` -> `collection_method` on subscriptions
  2019-12-03 - deprecated Customer tax fields removed (not used here)
  2020-08-27 - customer.sources and .subscriptions no longer auto-expand;
               use stripe.Customer.retrieve_source/create_source and
               stripe.Subscription.create(customer=id) instead
  2022-08-01 - Checkout Session overhaul (not used here)
  2022-11-15 - `charges` removed from PaymentIntent, Charge refunds no longer
               auto-expand (neither used here)
  2023-08-16 - automatic payment methods on by default for PaymentIntents
               (not used here)
  2024-04-10 - `rendering_options` -> `rendering` on invoices, `features`
               renamed on Product (neither used here)
  2024-09-30 - Acacia release, new monthly versioning model begins
  2025-03-31 - basil: current_period_end/start moved from subscription root
               to subscription items; handled via get_current_period_end().
               invoice.payment_intent removed; replaced by
               invoice.confirmation_secret.client_secret for SCA/3DS flows.
  2025-09-30 - clover: flexible billing mode default, iterations removed from
               subscription schedules, Discount.coupon -> Discount.source
               (none used here)
  2026-03-25 - dahlia: cancellation_reason enum expanded (not checked here)

Payment Intents migration (Phase 2):
  ChargeService.create() uses stripe.PaymentIntent.create(confirm=True) without
  off_session=True. When Stripe requires 3DS/SCA, the intent status is
  "requires_action" and PaymentActionRequired is raised carrying the
  client_secret and payment_intent_id for client-side confirmCardPayment().
  After the client confirms, confirm_payment_intent() retrieves the PI, verifies
  it succeeded, and returns (latest_charge, payment_method_id).

  Saved cards: new saves use PaymentMethods (pm_xxx) via save_card(). Existing
  customers' Sources/Cards (card_xxx/src_xxx) continue to work as payment_method
  in PaymentIntents per the Stripe transitioning guide.
"""

# Third Party
import stripe

# Squarelet
from squarelet.organizations.payments.base import (
    ChargeService,
    CustomerService,
    InvoiceService,
    PaymentActionRequired,
    PaymentProvider,
    PlanService,
    SubscriptionService,
)

CURRENT_API_VERSION = "2026-03-25.dahlia"


class StripeModernCustomerService(CustomerService):
    """Customer operations using current Stripe Payment Methods API."""

    def create(self, description, email, name):
        return stripe.Customer.create(
            description=description,
            email=email,
            name=name,
        )

    def retrieve(self, customer_id):
        return stripe.Customer.retrieve(customer_id)

    def modify(self, customer_id, **kwargs):
        return stripe.Customer.modify(customer_id, **kwargs)

    def save_card(self, stripe_customer, token):
        """Save a card token as the customer's default payment method."""
        pm = stripe.PaymentMethod.create(type="card", card={"token": token})
        stripe.PaymentMethod.attach(pm.id, customer=stripe_customer.id)
        stripe.Customer.modify(
            stripe_customer.id,
            invoice_settings={"default_payment_method": pm.id},
        )
        return pm

    def remove_payment_method(self, customer_id, source_id):
        """Remove a saved card. Handles both PaymentMethods (pm_) and Sources."""
        if source_id and source_id.startswith("pm_"):
            stripe.PaymentMethod.detach(source_id)
            stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": ""},
            )
        else:
            stripe.Customer.delete_source(customer_id, source_id)

    def retrieve_source(self, customer_id, source_id):
        # sources no longer auto-expand as of API version 2020-08-27
        return stripe.Customer.retrieve_source(customer_id, source_id)

    def add_source(self, stripe_customer, token):
        """Create and attach a PaymentMethod for a single charge."""
        pm = stripe.PaymentMethod.create(type="card", card={"token": token})
        stripe.PaymentMethod.attach(pm.id, customer=stripe_customer.id)
        return pm

    def remove_source(self, source_or_pm):
        """Detach a temporary PaymentMethod after a one-time charge.

        Accepts a PM object (with .id) or a PM ID string.
        """
        pm_id = source_or_pm if isinstance(source_or_pm, str) else source_or_pm.id
        stripe.PaymentMethod.detach(pm_id)

    def get_payment_method(self, stripe_customer):
        """Return the default PaymentMethod or legacy Source, or None."""
        invoice_settings = stripe_customer.invoice_settings
        pm_id = invoice_settings and invoice_settings.default_payment_method
        if pm_id:
            return stripe.PaymentMethod.retrieve(pm_id)
        if stripe_customer.default_source:
            source = stripe.Customer.retrieve_source(
                stripe_customer.id, stripe_customer.default_source
            )
            if source.object == "card":
                return source
        return None

    def retrieve_payment_method(self, pm_id):
        """Retrieve a PaymentMethod object by ID."""
        return stripe.PaymentMethod.retrieve(pm_id)


class StripeModernSubscriptionService(SubscriptionService):
    """Subscription operations using current Stripe API."""

    def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        stripe_customer,
        plan_id,
        quantity,
        billing,
        metadata,
        days_until_due,
        billing_cycle_anchor=None,
        cancel_at_period_end=False,
    ):
        # `billing` was renamed to `collection_method` in API version 2019-10-17
        # subscriptions no longer auto-expand as of API version 2020-08-27
        # latest_invoice.confirmation_secret replaces latest_invoice.payment_intent
        # for SCA/3DS detection as of API version 2025-03-31.basil
        params = {
            "customer": stripe_customer.id,
            "items": [{"plan": plan_id, "quantity": quantity}],
            "collection_method": billing,
            "metadata": metadata,
            "days_until_due": days_until_due,
            "cancel_at_period_end": cancel_at_period_end,
            "expand": ["latest_invoice.confirmation_secret"],
        }
        if billing_cycle_anchor is not None:
            params["billing_cycle_anchor"] = billing_cycle_anchor
            params["proration_behavior"] = "create_prorations"
        return stripe.Subscription.create(**params)

    def retrieve(self, subscription_id):
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except stripe.InvalidRequestError:  # pragma: no cover
            return None

    def modify(self, subscription_id, **kwargs):
        # `billing` -> `collection_method` may appear in kwargs from direct
        # modify() calls; translate if present
        if "billing" in kwargs:
            kwargs["collection_method"] = kwargs.pop("billing")
        return stripe.Subscription.modify(subscription_id, **kwargs)

    def cancel_at_period_end(self, stripe_subscription):
        return stripe.Subscription.modify(
            stripe_subscription.id,
            cancel_at_period_end=True,
        )

    def delete(self, stripe_subscription):
        stripe_subscription.delete()

    def get_current_period_end(self, stripe_subscription):
        # current_period_end moved from subscription root to subscription items
        # in API version 2025-03-31.basil
        items = stripe_subscription.items
        if items and items.data:
            return items.data[0].current_period_end
        return None


class StripeModernChargeService(ChargeService):
    """Charge operations using PaymentIntents."""

    def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        amount,
        currency,
        customer,
        description,
        source,
        metadata,
        statement_descriptor_suffix,
        idempotency_key,
    ):
        # `source` is a PaymentMethod (pm_) or a legacy Source/Card (card_/src_)
        # attached to the customer. Stripe accepts all as `payment_method` in
        # PaymentIntents per the Payment Methods transitioning guide.
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            customer=customer.id,
            payment_method=source.id,
            description=description,
            metadata=metadata,
            statement_descriptor_suffix=statement_descriptor_suffix,
            confirm=True,
            automatic_payment_methods={
                "enabled": True,
                "allow_redirects": "never",
            },
            expand=["latest_charge"],
            idempotency_key=idempotency_key,
        )
        if intent.status == "requires_action":
            raise PaymentActionRequired(intent.client_secret, intent.id)
        return intent.latest_charge

    def retrieve(self, charge_id):
        return stripe.Charge.retrieve(charge_id)

    def confirm_payment_intent(self, payment_intent_id):
        """Retrieve a succeeded PaymentIntent and return (latest_charge, pm_id)."""
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id, expand=["latest_charge"]
        )
        if intent.status != "succeeded":
            raise ValueError(
                f"PaymentIntent {payment_intent_id} has status {intent.status!r},"
                " expected 'succeeded'"
            )
        return intent.latest_charge, intent.payment_method


class StripeModernInvoiceService(InvoiceService):
    """Invoice operations using current Stripe API."""

    def retrieve(self, invoice_id, expand=None):
        if expand:
            return stripe.Invoice.retrieve(invoice_id, expand=expand)
        return stripe.Invoice.retrieve(invoice_id)

    def pay(self, stripe_invoice, paid_out_of_band=False):
        stripe_invoice.pay(paid_out_of_band=paid_out_of_band)

    def modify(self, invoice_id, **kwargs):
        return stripe.Invoice.modify(invoice_id, **kwargs)

    def mark_uncollectible(self, invoice_id):
        stripe.Invoice.mark_uncollectible(invoice_id)


class StripeModernPlanService(PlanService):
    """Plan and Product operations using Stripe Plans API."""

    def create(self, plan_id, currency, interval, product, **kwargs):
        return stripe.Plan.create(
            id=plan_id,
            currency=currency,
            interval=interval,
            product=product,
            **kwargs,
        )

    def retrieve(self, plan_id):
        return stripe.Plan.retrieve(id=plan_id)

    def delete(self, stripe_plan):
        stripe_plan.delete()

    def retrieve_product(self, product_id):
        return stripe.Product.retrieve(id=product_id)

    def delete_product(self, stripe_product):
        stripe_product.delete()


class StripeModernProvider(PaymentProvider):
    """
    Payment provider targeting current Stripe API versions.

    Translations from legacy parameter names to current API names are
    handled within each service method so call sites remain unchanged.
    """

    def __init__(self, api_key, api_version=CURRENT_API_VERSION):
        stripe.api_key = api_key
        stripe.api_version = api_version
        self._customer_service = StripeModernCustomerService()
        self._subscription_service = StripeModernSubscriptionService()
        self._charge_service = StripeModernChargeService()
        self._invoice_service = StripeModernInvoiceService()
        self._plan_service = StripeModernPlanService()

    def get_customer_service(self) -> CustomerService:
        return self._customer_service

    def get_subscription_service(self) -> SubscriptionService:
        return self._subscription_service

    def get_charge_service(self) -> ChargeService:
        return self._charge_service

    def get_invoice_service(self) -> InvoiceService:
        return self._invoice_service

    def get_plan_service(self) -> PlanService:
        return self._plan_service
