# Standard Library
from unittest.mock import Mock

# Third Party
import pytest


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

    def test_card_existing(self, customer_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "card"
        customer = customer_factory.build()
        assert mocked.sources.retrieve.return_value == customer.card
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_ach(self, customer_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "ach"
        customer = customer_factory.build()
        assert customer.card is None
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_blank(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        customer = customer_factory.build()
        assert customer.card is None

    def test_card_display(self, customer_factory, mocker):
        brand = "Visa"
        last4 = "4242"
        mocker.patch(
            "squarelet.organizations.models.Customer.card", brand=brand, last4=last4
        )
        customer = customer_factory.build(customer_id="customer_id")
        assert customer.card_display == f"{brand}: x{last4}"

    def test_card_display_empty(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        customer = customer_factory.build()
        assert customer.card_display == ""

    def test_save_card(self, customer_factory, mocker):
        token = "token"
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer"
        )
        customer = customer_factory.build()
        customer.save_card(token)
        assert mocked_customer.source == token
        mocked_customer.save.assert_called_once()
