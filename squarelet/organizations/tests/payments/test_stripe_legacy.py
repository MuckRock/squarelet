# Third Party
import pytest

# Squarelet
from squarelet.organizations.payments.providers.stripe_legacy import (
    StripeLegacyCustomerService,
    StripeLegacySubscriptionService,
)


@pytest.fixture
def customer_service():
    return StripeLegacyCustomerService()


@pytest.fixture
def subscription_service():
    return StripeLegacySubscriptionService()


class TestLegacyCustomerService:
    def test_retrieve_source(self, customer_service, mocker):
        source_id = "src_123"
        mock_customer = mocker.MagicMock()
        result = customer_service.retrieve_source(mock_customer, source_id)
        mock_customer.sources.retrieve.assert_called_once_with(source_id)
        assert result == mock_customer.sources.retrieve.return_value

    def test_add_source(self, customer_service, mocker):
        token = "tok_123"
        mock_customer = mocker.MagicMock()
        result = customer_service.add_source(mock_customer, token)
        mock_customer.sources.create.assert_called_once_with(source=token)
        assert result == mock_customer.sources.create.return_value


class TestLegacySubscriptionService:
    def test_create_uses_billing_parameter(self, subscription_service, mocker):
        mock_customer = mocker.MagicMock()
        subscription_service.create(
            stripe_customer=mock_customer,
            plan_id="plan_123",
            quantity=5,
            billing="charge_automatically",
            metadata={"action": "test"},
            days_until_due=None,
        )
        mock_customer.subscriptions.create.assert_called_once_with(
            items=[{"plan": "plan_123", "quantity": 5}],
            billing="charge_automatically",
            metadata={"action": "test"},
            days_until_due=None,
        )

    def test_get_current_period_end(self, subscription_service, mocker):
        mock_sub = mocker.MagicMock()
        mock_sub.current_period_end = 1700000000
        assert subscription_service.get_current_period_end(mock_sub) == 1700000000

    def test_get_current_period_end_missing(self, subscription_service, mocker):
        mock_sub = mocker.MagicMock(spec=[])
        assert subscription_service.get_current_period_end(mock_sub) is None
