"""
Abstract interfaces for the payment provider abstraction layer.

These interfaces decouple business logic from Stripe-specific implementation,
allowing the legacy Stripe 2.x provider and the modern Stripe 11.x provider
to be swapped via a feature flag.

Phase 2 note: service methods return raw Stripe objects. Phase 3 will
introduce domain dataclasses as return types when the modern provider is built.
"""

# Standard Library
from abc import ABC, abstractmethod


class CustomerService(ABC):
    """Manages Stripe Customer objects and their payment sources."""

    @abstractmethod
    def create(self, description, email, name):
        """Create a new customer in the payment provider."""

    @abstractmethod
    def retrieve(self, customer_id):
        """Retrieve an existing customer by ID."""

    @abstractmethod
    def modify(self, customer_id, **kwargs):
        """Modify an existing customer's attributes."""

    @abstractmethod
    def save_card(self, stripe_customer, token):
        """Set a card token as the customer's default payment source."""

    @abstractmethod
    def remove_card(self, customer_id, source_id):
        """Remove a payment source from a customer."""

    @abstractmethod
    def retrieve_source(self, stripe_customer, source_id):
        """Retrieve a specific payment source for a customer."""

    @abstractmethod
    def add_source(self, stripe_customer, token):
        """Add a non-default payment source to a customer."""


class SubscriptionService(ABC):
    """Manages Stripe Subscription objects."""

    @abstractmethod
    def create(  # pylint: disable=too-many-positional-arguments
        self,
        stripe_customer,
        plan_id,
        quantity,
        billing,
        metadata,
        days_until_due,
    ):
        """Create a new subscription for a customer."""

    @abstractmethod
    def retrieve(self, subscription_id):
        """Retrieve an existing subscription by ID. Returns None if not found."""

    @abstractmethod
    def modify(self, subscription_id, **kwargs):
        """Modify an existing subscription."""

    @abstractmethod
    def cancel_at_period_end(self, stripe_subscription):
        """Mark a subscription to cancel at the end of the current period."""

    @abstractmethod
    def delete(self, stripe_subscription):
        """Immediately cancel and delete a subscription."""


class ChargeService(ABC):
    """Manages Stripe Charge objects."""

    @abstractmethod
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
        """Create a charge against a customer's payment source."""

    @abstractmethod
    def retrieve(self, charge_id):
        """Retrieve an existing charge by ID."""


class InvoiceService(ABC):
    """Manages Stripe Invoice objects."""

    @abstractmethod
    def retrieve(self, invoice_id):
        """Retrieve an existing invoice by ID."""

    @abstractmethod
    def pay(self, stripe_invoice, paid_out_of_band=False):
        """Mark an invoice as paid."""

    @abstractmethod
    def mark_uncollectible(self, invoice_id):
        """Mark an invoice as uncollectible."""


class PlanService(ABC):
    """Manages Stripe Plan and Product objects."""

    @abstractmethod
    def create(self, plan_id, currency, interval, product, **kwargs):
        """Create a plan in the payment provider."""

    @abstractmethod
    def retrieve(self, plan_id):
        """Retrieve an existing plan by ID."""

    @abstractmethod
    def delete(self, stripe_plan):
        """Delete a plan."""

    @abstractmethod
    def retrieve_product(self, product_id):
        """Retrieve a product by ID."""

    @abstractmethod
    def delete_product(self, stripe_product):
        """Delete a product."""


class PaymentProvider(ABC):
    """
    Top-level provider interface.

    Instantiated via get_payment_provider() and holds provider configuration
    (API keys, API version). Returns configured service instances for each
    payment domain.
    """

    @abstractmethod
    def get_customer_service(self) -> CustomerService:
        """Return the customer service for this provider."""

    @abstractmethod
    def get_subscription_service(self) -> SubscriptionService:
        """Return the subscription service for this provider."""

    @abstractmethod
    def get_charge_service(self) -> ChargeService:
        """Return the charge service for this provider."""

    @abstractmethod
    def get_invoice_service(self) -> InvoiceService:
        """Return the invoice service for this provider."""

    @abstractmethod
    def get_plan_service(self) -> PlanService:
        """Return the plan service for this provider."""
