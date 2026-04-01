"""Factory function for obtaining the configured payment provider."""

# Django
from django.conf import settings

# Squarelet
from squarelet.organizations.payments.base import PaymentProvider


def get_payment_provider() -> PaymentProvider:
    """
    Return the configured payment provider instance.

    Reads STRIPE_PROVIDER from settings (default: 'legacy').
    Set STRIPE_PROVIDER='modern' to use the current-API provider.
    """
    # pylint: disable=import-outside-toplevel
    # imported here to avoid circular imports at module load time
    provider_type = settings.STRIPE_PROVIDER

    if provider_type == "legacy":
        from squarelet.organizations.payments.providers.stripe_legacy import (
            StripeLegacyProvider,
        )

        return StripeLegacyProvider(
            api_key=settings.STRIPE_SECRET_KEY,
            api_version="2018-09-24",
        )

    if provider_type == "modern":
        from squarelet.organizations.payments.providers.stripe_modern import (
            StripeModernProvider,
        )

        return StripeModernProvider(
            api_key=settings.STRIPE_SECRET_KEY,
        )

    raise ValueError(
        f"Unknown STRIPE_PROVIDER '{provider_type}'. "
        "Valid options: 'legacy', 'modern'"
    )
