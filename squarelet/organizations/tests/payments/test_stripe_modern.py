# Third Party
import pytest

# Squarelet
from squarelet.organizations.payments.providers.stripe_modern import (
    StripeModernCustomerService,
    StripeModernSubscriptionService,
)


@pytest.fixture
def customer_service():
    return StripeModernCustomerService()


@pytest.fixture
def subscription_service():
    return StripeModernSubscriptionService()


class TestModernCustomerService:
    def test_retrieve_source(self, customer_service, mocker):
        customer_id = "cus_123"
        source_id = "src_123"
        mock_customer = mocker.MagicMock(id=customer_id)
        mock_retrieve = mocker.patch("stripe.Customer.retrieve_source")
        result = customer_service.retrieve_source(mock_customer, source_id)
        mock_retrieve.assert_called_once_with(customer_id, source_id)
        assert result == mock_retrieve.return_value

    def test_add_source(self, customer_service, mocker):
        customer_id = "cus_123"
        token = "tok_123"
        mock_customer = mocker.MagicMock(id=customer_id)
        mock_create = mocker.patch("stripe.Customer.create_source")
        result = customer_service.add_source(mock_customer, token)
        mock_create.assert_called_once_with(customer_id, source=token)
        assert result == mock_create.return_value


class TestModernSubscriptionService:
    def test_create_uses_collection_method(self, subscription_service, mocker):
        mock_customer = mocker.MagicMock(id="cus_123")
        mock_create = mocker.patch("stripe.Subscription.create")
        subscription_service.create(
            stripe_customer=mock_customer,
            plan_id="plan_123",
            quantity=5,
            billing="charge_automatically",
            metadata={"action": "test"},
            days_until_due=None,
        )
        mock_create.assert_called_once_with(
            customer="cus_123",
            items=[{"plan": "plan_123", "quantity": 5}],
            collection_method="charge_automatically",
            metadata={"action": "test"},
            days_until_due=None,
        )

    def test_create_translates_send_invoice(self, subscription_service, mocker):
        mock_customer = mocker.MagicMock(id="cus_123")
        mock_create = mocker.patch("stripe.Subscription.create")
        subscription_service.create(
            stripe_customer=mock_customer,
            plan_id="plan_123",
            quantity=1,
            billing="send_invoice",
            metadata={},
            days_until_due=30,
        )
        mock_create.assert_called_once_with(
            customer="cus_123",
            items=[{"plan": "plan_123", "quantity": 1}],
            collection_method="send_invoice",
            metadata={},
            days_until_due=30,
        )

    def test_modify_translates_billing_to_collection_method(
        self, subscription_service, mocker
    ):
        mock_modify = mocker.patch("stripe.Subscription.modify")
        subscription_service.modify(
            "sub_123",
            billing="charge_automatically",
            cancel_at_period_end=False,
        )
        mock_modify.assert_called_once_with(
            "sub_123",
            collection_method="charge_automatically",
            cancel_at_period_end=False,
        )

    def test_modify_without_billing_passes_kwargs_unchanged(
        self, subscription_service, mocker
    ):
        mock_modify = mocker.patch("stripe.Subscription.modify")
        subscription_service.modify("sub_123", cancel_at_period_end=True)
        mock_modify.assert_called_once_with("sub_123", cancel_at_period_end=True)

    def test_get_current_period_end(self, subscription_service, mocker):
        mock_item = mocker.MagicMock(current_period_end=1700000000)
        mock_sub = mocker.MagicMock()
        mock_sub.items.data = [mock_item]
        assert subscription_service.get_current_period_end(mock_sub) == 1700000000

    def test_get_current_period_end_no_items(self, subscription_service, mocker):
        mock_sub = mocker.MagicMock()
        mock_sub.items.data = []
        assert subscription_service.get_current_period_end(mock_sub) is None

    def test_get_current_period_end_no_items_attr(self, subscription_service, mocker):
        mock_sub = mocker.MagicMock(spec=[])
        assert subscription_service.get_current_period_end(mock_sub) is None
