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
               to subscription items; handled via get_current_period_end()
  2025-09-30 - clover: flexible billing mode default, iterations removed from
               subscription schedules, Discount.coupon -> Discount.source
               (none used here)
  2026-03-25 - dahlia: cancellation_reason enum expanded (not checked here)
"""

# Third Party
import stripe

# Squarelet
from squarelet.organizations.payments.base import (
    ChargeService,
    CustomerService,
    InvoiceService,
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
        """Set a card token as the customer's default source."""
        stripe.Customer.modify(stripe_customer.id, source=token)

    def remove_card(self, customer_id, source_id):
        stripe.Customer.delete_source(customer_id, source_id)

    def retrieve_source(self, stripe_customer, source_id):
        # sources no longer auto-expand as of API version 2020-08-27
        return stripe.Customer.retrieve_source(stripe_customer.id, source_id)

    def add_source(self, stripe_customer, token):
        # sources no longer auto-expand as of API version 2020-08-27
        return stripe.Customer.create_source(stripe_customer.id, source=token)


class StripeModernSubscriptionService(SubscriptionService):
    """Subscription operations using current Stripe API."""

    def create(  # pylint: disable=too-many-positional-arguments
        self,
        stripe_customer,
        plan_id,
        quantity,
        billing,
        metadata,
        days_until_due,
    ):
        # `billing` was renamed to `collection_method` in API version 2019-10-17
        # subscriptions no longer auto-expand as of API version 2020-08-27
        return stripe.Subscription.create(
            customer=stripe_customer.id,
            items=[{"plan": plan_id, "quantity": quantity}],
            collection_method=billing,
            metadata=metadata,
            days_until_due=days_until_due,
        )

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
        stripe.Subscription.modify(
            stripe_subscription.id,
            cancel_at_period_end=True,
        )

    def delete(self, stripe_subscription):
        stripe_subscription.delete()

    def get_current_period_end(self, stripe_subscription):
        # current_period_end moved from subscription root to subscription items
        # in API version 2025-03-31.basil
        items = getattr(stripe_subscription, "items", None)
        if items and items.data:
            return getattr(items.data[0], "current_period_end", None)
        return None


class StripeModernChargeService(ChargeService):
    """Charge operations using Stripe direct charges."""

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
        return stripe.Charge.create(
            amount=amount,
            currency=currency,
            customer=customer,
            description=description,
            source=source,
            metadata=metadata,
            statement_descriptor_suffix=statement_descriptor_suffix,
            idempotency_key=idempotency_key,
        )

    def retrieve(self, charge_id):
        return stripe.Charge.retrieve(charge_id)


class StripeModernInvoiceService(InvoiceService):
    """Invoice operations using current Stripe API."""

    def retrieve(self, invoice_id):
        return stripe.Invoice.retrieve(invoice_id)

    def pay(self, stripe_invoice, paid_out_of_band=False):
        stripe_invoice.pay(paid_out_of_band=paid_out_of_band)

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
