# Django
from django.utils import timezone

# Standard Library
from datetime import timedelta
from unittest.mock import MagicMock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import Invoice


def create_mock_stripe_invoice(invoice_id, amount_due, status, created, due_date=None):
    """
    Create a mock Stripe invoice object that supports dictionary-style access.

    This helper simulates how Stripe API objects work (they inherit from dict),
    allowing tests to use the same mock structure consistently.
    """
    mock_invoice = MagicMock()
    invoice_data = {
        "id": invoice_id,
        "amount_due": amount_due,
        "status": status,
        "created": created,
        "due_date": due_date,
    }
    mock_invoice.__getitem__ = MagicMock(side_effect=lambda k: invoice_data[k])
    mock_invoice.get = MagicMock(
        side_effect=lambda k, default=None: invoice_data.get(k, default)
    )
    # Also support property access (e.g., mock_invoice.id)
    mock_invoice.id = invoice_id
    return mock_invoice


class TestInvoice:
    """Unit tests for Invoice model"""

    def test_str(self, invoice_factory):
        invoice = invoice_factory.build(
            invoice_id="in_12345", amount=10000, status="open"
        )
        assert str(invoice) == "Invoice in_12345 - $100.00 (open)"

    def test_amount_dollars(self, invoice_factory):
        invoice = invoice_factory.build(amount=12345)
        assert invoice.amount_dollars == 123.45

    @pytest.mark.django_db
    def test_is_overdue_true_for_past_due(self, invoice_factory):
        """Test is_overdue returns True for open invoice past due date"""
        past_due_date = timezone.now().date() - timedelta(days=1)
        invoice = invoice_factory(status="open", due_date=past_due_date)
        assert invoice.is_overdue is True

    @pytest.mark.django_db
    def test_is_overdue_false_for_future_due(self, invoice_factory):
        """Test is_overdue returns False for open invoice with future due date"""
        future_due_date = timezone.now().date() + timedelta(days=30)
        invoice = invoice_factory(status="open", due_date=future_due_date)
        assert invoice.is_overdue is False

    @pytest.mark.django_db
    def test_is_overdue_false_for_paid_invoice(self, invoice_factory):
        """Test is_overdue returns False for paid invoice even if past due"""
        past_due_date = timezone.now().date() - timedelta(days=30)
        invoice = invoice_factory(status="paid", due_date=past_due_date)
        assert invoice.is_overdue is False

    @pytest.mark.django_db
    def test_is_overdue_false_for_no_due_date(self, invoice_factory):
        """Test is_overdue returns False when invoice has no due date"""
        invoice = invoice_factory(status="open", due_date=None)
        assert invoice.is_overdue is False

    def test_amount_none(self, invoice_factory):
        """Test formatting logic when amount is None"""
        invoice = invoice_factory.build(
            invoice_id="in_12345", amount=None, status="open"
        )
        assert invoice.amount_dollars == 0.0
        assert str(invoice) == "Invoice in_12345 - $0.00 (open)"

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_dict_access(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe with dictionary (webhook scenario)"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        # Simulate webhook data - plain dictionary
        stripe_invoice_dict = {
            "id": "in_webhook123",
            "amount_due": 5000,  # $50.00
            "status": "open",
            "created": 1234567890,
            "due_date": 1234657890,  # 30 days later
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, subscription
        )

        assert created is True
        assert invoice.invoice_id == "in_webhook123"
        assert invoice.organization == organization
        assert invoice.subscription == subscription
        assert invoice.amount == 5000
        assert invoice.status == "open"
        assert invoice.due_date is not None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_object_access(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe with Stripe object (API scenario)"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        # Simulate Stripe API object using helper function
        mock_stripe_invoice = create_mock_stripe_invoice(
            invoice_id="in_api456",
            amount_due=10000,  # $100.00
            status="paid",
            created=1234567890,
            due_date=None,
        )

        invoice, created = Invoice.create_or_update_from_stripe(
            mock_stripe_invoice, organization, subscription
        )

        assert created is True
        assert invoice.invoice_id == "in_api456"
        assert invoice.organization == organization
        assert invoice.subscription == subscription
        assert invoice.amount == 10000
        assert invoice.status == "paid"
        assert invoice.due_date is None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_updates_existing(
        self, organization_factory, invoice_factory
    ):
        """Test that create_or_update_from_stripe updates existing invoices"""
        organization = organization_factory()
        existing_invoice = invoice_factory(
            invoice_id="in_existing789",
            organization=organization,
            amount=5000,
            status="open",
        )

        # Update with new data
        stripe_invoice_dict = {
            "id": "in_existing789",
            "amount_due": 7500,  # Changed amount
            "status": "paid",  # Changed status
            "created": 1234567890,
            "due_date": None,
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, None
        )

        assert created is False
        assert invoice.id == existing_invoice.id
        assert invoice.amount == 7500
        assert invoice.status == "paid"

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_no_due_date(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe handles None due_date correctly"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        stripe_invoice_dict = {
            "id": "in_no_due_date",
            "amount_due": 2000,
            "status": "draft",
            "created": 1234567890,
            "due_date": None,  # No due date
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, subscription
        )

        assert created is True
        assert invoice.due_date is None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_no_subscription(self, organization_factory):
        """Test create_or_update_from_stripe works without subscription"""
        organization = organization_factory()

        stripe_invoice_dict = {
            "id": "in_no_sub",
            "amount_due": 3000,
            "status": "open",
            "created": 1234567890,
            "due_date": 1234657890,
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, None
        )

        assert created is True
        assert invoice.subscription is None
        assert invoice.organization == organization

    @pytest.mark.django_db
    def test_mark_uncollectible_in_stripe_success(self, invoice_factory, mocker):
        """Test mark_uncollectible_in_stripe successfully marks invoice"""
        invoice = invoice_factory(invoice_id="in_test123", status="open")

        # Mock the Stripe API request
        mock_mark = mocker.patch("stripe.Invoice.mark_uncollectible")

        # Call the method
        invoice.mark_uncollectible_in_stripe()

        # Verify Stripe API was called correctly
        mock_mark.assert_called_once_with("in_test123")

    @pytest.mark.django_db
    def test_mark_uncollectible_in_stripe_stripe_error(self, invoice_factory, mocker):
        """Test mark_uncollectible_in_stripe handles Stripe errors"""
        invoice = invoice_factory(invoice_id="in_error123", status="open")

        # Mock the Stripe API request to raise an error
        mocker.patch(
            "stripe.Invoice.mark_uncollectible",
            side_effect=stripe.error.InvalidRequestError(
                "This invoice has already been marked uncollectible",
                "invoice",
            ),
        )

        # Should raise the Stripe error
        with pytest.raises(stripe.error.InvalidRequestError):
            invoice.mark_uncollectible_in_stripe()
