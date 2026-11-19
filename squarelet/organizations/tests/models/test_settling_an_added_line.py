"""An added line's charge needs the card only when one pays for it."""

# Standard Library
from unittest.mock import Mock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.payments.base import PaymentActionRequired


@pytest.fixture(name="open_invoice")
def open_invoice_fixture(mocker):
    """A Stripe subscription whose latest invoice is still unpaid."""
    provider = mocker.patch(
        "squarelet.organizations.models.payment.get_payment_provider"
    ).return_value
    invoice = Mock(status="open")
    invoice.confirmation_secret.client_secret = "pi_123_secret_456"
    provider.get_invoice_service.return_value.retrieve.return_value = invoice
    return Mock(latest_invoice="in_123")


@pytest.mark.django_db()
class TestSettleAddedLine:
    def test_an_invoiced_organization_is_not_asked_for_a_card(
        self, subscription_factory, open_invoice
    ):
        subscription = subscription_factory(
            interval="annual", collection_method="send_invoice"
        )

        subscription.settle_added_line(open_invoice)

    def test_a_card_payer_with_an_unpaid_charge_must_authenticate(
        self, subscription_factory, open_invoice
    ):
        subscription = subscription_factory()

        with pytest.raises(PaymentActionRequired):
            subscription.settle_added_line(open_invoice)
