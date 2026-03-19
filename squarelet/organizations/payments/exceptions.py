"""Payment-specific exceptions for the provider abstraction layer."""


class PaymentError(Exception):
    """Base exception for all payment errors."""


class CustomerNotFoundError(PaymentError):
    """Raised when a customer cannot be found in the payment provider."""


class CardError(PaymentError):
    """Raised when a card operation fails (declined, invalid, etc.)."""


class SubscriptionError(PaymentError):
    """Raised when a subscription operation fails."""


class InvoiceError(PaymentError):
    """Raised when an invoice operation fails."""


class PaymentProviderError(PaymentError):
    """Raised when the payment provider itself encounters an error."""
