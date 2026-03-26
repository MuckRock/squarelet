"""
Legacy Stripe provider wrapping Stripe Python 2.x with API version 2018-09-24.

This provider preserves all existing behavior exactly — it is a structural
extraction of the stripe.* calls currently scattered across models, querysets,
and tasks. No behavioral changes are made here.

All Stripe API calls are wrapped with stripe_retry_on_error to handle
transient APIConnectionError and RateLimitError consistently.
"""

# Third Party
import stripe

# Squarelet
from squarelet.core.utils import stripe_retry_on_error
from squarelet.organizations.payments.base import (
    ChargeService,
    CustomerService,
    InvoiceService,
    PaymentProvider,
    PlanService,
    SubscriptionService,
)


class StripeLegacyCustomerService(CustomerService):
    """Customer operations using Stripe 2.x Sources API."""

    def create(self, description, email, name):
        return stripe_retry_on_error(
            stripe.Customer.create,
            description=description,
            email=email,
            name=name,
        )

    def retrieve(self, customer_id):
        return stripe_retry_on_error(stripe.Customer.retrieve, customer_id)

    def modify(self, customer_id, **kwargs):
        return stripe_retry_on_error(stripe.Customer.modify, customer_id, **kwargs)

    def save_card(self, stripe_customer, token):
        """Set a card token as the customer's default source."""
        stripe_customer.source = token
        stripe_retry_on_error(stripe_customer.save)

    def remove_card(self, customer_id, source_id):
        stripe_retry_on_error(stripe.Customer.delete_source, customer_id, source_id)

    def retrieve_source(self, stripe_customer, source_id):
        return stripe_retry_on_error(stripe_customer.sources.retrieve, source_id)

    def add_source(self, stripe_customer, token):
        return stripe_retry_on_error(stripe_customer.sources.create, source=token)


class StripeLegacySubscriptionService(SubscriptionService):
    """Subscription operations using Stripe 2.x Plans API."""

    def create(  # pylint: disable=too-many-positional-arguments
        self,
        stripe_customer,
        plan_id,
        quantity,
        billing,
        metadata,
        days_until_due,
    ):
        return stripe_retry_on_error(
            stripe_customer.subscriptions.create,
            items=[{"plan": plan_id, "quantity": quantity}],
            billing=billing,
            metadata=metadata,
            days_until_due=days_until_due,
        )

    def retrieve(self, subscription_id):
        try:
            return stripe_retry_on_error(stripe.Subscription.retrieve, subscription_id)
        except stripe.InvalidRequestError:  # pragma: no cover
            return None

    def modify(self, subscription_id, **kwargs):
        return stripe_retry_on_error(
            stripe.Subscription.modify, subscription_id, **kwargs
        )

    def cancel_at_period_end(self, stripe_subscription):
        stripe_subscription.cancel_at_period_end = True
        stripe_retry_on_error(stripe_subscription.save)

    def delete(self, stripe_subscription):
        stripe_retry_on_error(stripe_subscription.delete)


class StripeLegacyChargeService(ChargeService):
    """Charge operations using Stripe 2.x direct charges."""

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
        return stripe_retry_on_error(
            stripe.Charge.create,
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
        return stripe_retry_on_error(stripe.Charge.retrieve, charge_id)


class StripeLegacyInvoiceService(InvoiceService):
    """Invoice operations using Stripe 2.x."""

    def retrieve(self, invoice_id):
        return stripe_retry_on_error(stripe.Invoice.retrieve, invoice_id)

    def pay(self, stripe_invoice, paid_out_of_band=False):
        stripe_retry_on_error(stripe_invoice.pay, paid_out_of_band=paid_out_of_band)

    def mark_uncollectible(self, invoice_id):
        """
        Mark an invoice uncollectible via direct API request.
        """
        stripe_retry_on_error(
            stripe.Invoice.mark_uncollectible,
            invoice_id,
        )


class StripeLegacyPlanService(PlanService):
    """Plan and Product operations using Stripe 2.x Plans API."""

    def create(self, plan_id, currency, interval, product, **kwargs):
        return stripe_retry_on_error(
            stripe.Plan.create,
            id=plan_id,
            currency=currency,
            interval=interval,
            product=product,
            **kwargs,
        )

    def retrieve(self, plan_id):
        return stripe_retry_on_error(stripe.Plan.retrieve, id=plan_id)

    def delete(self, stripe_plan):
        stripe_retry_on_error(stripe_plan.delete)

    def retrieve_product(self, product_id):
        return stripe_retry_on_error(stripe.Product.retrieve, id=product_id)

    def delete_product(self, stripe_product):
        stripe_retry_on_error(stripe_product.delete)


class StripeLegacyProvider(PaymentProvider):
    """
    Payment provider wrapping Stripe Python 2.x / API version 2018-09-24.

    Configures the global stripe module on instantiation and returns
    service instances for each payment domain.
    """

    def __init__(self, api_key, api_version):
        stripe.api_key = api_key
        stripe.api_version = api_version
        self._customer_service = StripeLegacyCustomerService()
        self._subscription_service = StripeLegacySubscriptionService()
        self._charge_service = StripeLegacyChargeService()
        self._invoice_service = StripeLegacyInvoiceService()
        self._plan_service = StripeLegacyPlanService()

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
