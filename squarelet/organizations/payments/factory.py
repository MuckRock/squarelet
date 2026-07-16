"""Factory function for obtaining the payment provider."""

# Django
from django.conf import settings

# Squarelet
from squarelet.organizations.payments.base import PaymentProvider
from squarelet.organizations.payments.providers.stripe_modern import (
    StripeModernProvider,
)


def get_payment_provider() -> PaymentProvider:
    """Return the configured payment provider instance."""
    return StripeModernProvider(api_key=settings.STRIPE_SECRET_KEY)
