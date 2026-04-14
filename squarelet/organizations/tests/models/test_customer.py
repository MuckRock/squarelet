# Standard Library
from unittest.mock import Mock

# Third Party
import pytest
import stripe


class TestCustomer:
    """Unit tests for Customer model"""

    def test_customer_existing(self, customer_factory, mocker):
        mocked = mocker.patch("stripe.Customer.retrieve")
        customer_id = "customer_id"
        customer = customer_factory.build(customer_id=customer_id)
        assert mocked.return_value == customer.stripe_customer
        mocked.assert_called_with(customer_id)

    @pytest.mark.django_db()
    def test_customer_new(self, customer_factory, mocker):
        customer_id = "customer_id"
        mock_customer = Mock(id=customer_id)
        mocked_create = mocker.patch(
            "stripe.Customer.create", return_value=mock_customer
        )
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        customer = customer_factory(customer_id=None)
        assert mock_customer == customer.stripe_customer
        mocked_create.assert_called_with(
            description=customer.organization.name,
            email=email,
            name=customer.organization.user_full_name,
        )
        customer.refresh_from_db()
        assert customer.customer_id == customer_id

    def test_source_existing(self, customer_factory, mocker):
        mock_stripe_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer"
        )
        mock_source = mocker.MagicMock(object="card")
        mock_get_payment_method = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_customer_service.return_value.get_payment_method
        mock_get_payment_method.return_value = mock_source
        customer = customer_factory.build()
        assert mock_source == customer.payment_method
        mock_get_payment_method.assert_called_once_with(mock_stripe_customer)

    def test_source_none(self, customer_factory, mocker):
        mock_stripe_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer"
        )
        mock_get_payment_method = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_customer_service.return_value.get_payment_method
        mock_get_payment_method.return_value = None
        customer = customer_factory.build()
        assert customer.payment_method is None
        mock_get_payment_method.assert_called_once_with(mock_stripe_customer)

    def test_card_legacy_source(self, customer_factory, mocker):
        """Legacy Source objects are returned as-is from customer.card."""
        mock_source = mocker.MagicMock(object="card")
        mocker.patch(
            "squarelet.organizations.models.Customer.payment_method",
            new_callable=mocker.PropertyMock,
            return_value=mock_source,
        )
        customer = customer_factory.build()
        assert customer.card is mock_source

    def test_card_payment_method(self, customer_factory, mocker):
        """PaymentMethod sources expose card details via .card sub-object."""
        mock_card_details = mocker.MagicMock(brand="Visa", last4="4242")
        mock_source = mocker.MagicMock(
            object="payment_method", type="card", card=mock_card_details
        )
        mocker.patch(
            "squarelet.organizations.models.Customer.payment_method",
            new_callable=mocker.PropertyMock,
            return_value=mock_source,
        )
        customer = customer_factory.build()
        assert customer.card is mock_card_details

    def test_card_none(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.payment_method",
            new_callable=mocker.PropertyMock,
            return_value=None,
        )
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_customer_service.return_value.get_card.return_value = None
        customer = customer_factory.build()
        assert customer.card is None

    def test_card_display(self, customer_factory, mocker):
        brand = "Visa"
        last4 = "4242"
        mock_card = mocker.MagicMock(brand=brand, last4=last4)
        mocker.patch(
            "squarelet.organizations.models.Customer.payment_details",
            new_callable=mocker.PropertyMock,
            return_value=mock_card,
        )
        customer = customer_factory.build(customer_id="customer_id")
        assert customer.payment_method_display == f"{brand}: x{last4}"

    def test_card_display_empty(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.payment_details",
            new_callable=mocker.PropertyMock,
            return_value=None,
        )
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_customer_service.return_value.get_card.return_value = None
        customer = customer_factory.build()
        assert customer.payment_method_display == ""

    def test_save_card(self, customer_factory, mocker):
        token = "token"
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer"
        )
        mocked_customer.id = "cus_test123"
        mock_pm = mocker.MagicMock(id="pm_new")
        mocker.patch("stripe.PaymentMethod.create", return_value=mock_pm)
        mock_attach = mocker.patch("stripe.PaymentMethod.attach")
        mock_modify = mocker.patch("stripe.Customer.modify")
        customer = customer_factory.build()
        customer.save_card(token)
        mock_attach.assert_called_once_with("pm_new", customer="cus_test123")
        mock_modify.assert_called_once_with(
            "cus_test123",
            invoice_settings={"default_payment_method": "pm_new"},
        )

    @pytest.mark.django_db()
    def test_customer_invalid_clears_and_creates_new(self, customer_factory, mocker):
        """Test that an invalid customer_id is cleared and a new customer is created"""
        old_customer_id = "cus_invalid_id"
        new_customer_id = "cus_new_id"

        # Mock stripe.Customer.retrieve to raise InvalidRequestError for old ID only
        def mock_retrieve(customer_id):
            if customer_id == old_customer_id:
                error = stripe.InvalidRequestError(
                    "No such customer: 'cus_invalid_id'; a similar object "
                    "exists in live mode, but a test mode key was used "
                    "to make this request.",
                    "id",
                )
                error.code = "resource_missing"
                raise error
            # If called with a different ID (e.g., new customer created by
            # another thread), return a mock customer
            return Mock(id=customer_id, name="Test Customer")

        mocked_retrieve = mocker.patch(
            "stripe.Customer.retrieve",
            side_effect=mock_retrieve,
        )

        # Mock stripe.Customer.create to return a new customer
        mock_new_customer = Mock(id=new_customer_id)
        mocked_create = mocker.patch(
            "stripe.Customer.create", return_value=mock_new_customer
        )

        # Create a customer with an invalid customer_id
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        customer = customer_factory(customer_id=old_customer_id)

        # Access stripe_customer property - should clear invalid ID and create new one
        result = customer.stripe_customer

        # Verify the retrieve was called with the old ID
        mocked_retrieve.assert_called_with(old_customer_id)

        # Verify a new customer was created
        mocked_create.assert_called_with(
            description=customer.organization.name,
            email=email,
            name=customer.organization.user_full_name,
        )

        # Verify the result is the new customer
        assert result == mock_new_customer

        # Verify the customer_id was updated in the database
        customer.refresh_from_db()
        assert customer.customer_id == new_customer_id
