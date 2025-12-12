# Standard Library
from unittest.mock import PropertyMock

# Third Party
import pytest


class TestCharge:
    """Unit tests for Charge model"""

    def test_str(self, charge_factory):
        charge = charge_factory.build()
        assert (
            str(charge)
            == f"${charge.amount / 100:.2f} charge to {charge.organization.name}"
        )

    def test_get_absolute_url(self, charge_factory):
        charge = charge_factory.build(pk=1)
        assert charge.get_absolute_url() == f"/organizations/~charge/{charge.pk}/"

    def test_amount_dollars(self, charge_factory):
        charge = charge_factory.build(amount=350)
        assert charge.amount_dollars == 3.50

    @pytest.mark.django_db()
    def test_send_receipt(self, charge_factory, mailoutbox, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.Charge.charge", new_callable=PropertyMock
        )
        mocked.return_value = {"source": {"brand": "Visa", "last4": "1234"}}

        emails = ["receipts@example.com", "foo@example.com"]
        charge = charge_factory()
        charge.organization.set_receipt_emails(emails)
        charge.send_receipt()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == "Receipt"
        assert set(mail.to) == set(emails)

    def test_items_no_fee(self, charge_factory):
        charge = charge_factory.build()
        assert charge.items() == [
            {"name": charge.description, "price": charge.amount_dollars}
        ]

    def test_items_fee(self, charge_factory):
        charge = charge_factory.build(amount=10500, fee_amount=5)
        assert charge.items() == [
            {"name": charge.description, "price": 100.00},
            {"name": "Processing Fee", "price": 5.00},
        ]
