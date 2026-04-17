# Third Party
import pytest

# Squarelet
from squarelet.organizations.payments.providers.stripe_legacy import (
    StripeLegacyChargeService,
    StripeLegacyCustomerService,
    StripeLegacySubscriptionService,
)

# pylint: disable=redefined-outer-name


@pytest.fixture
def customer_service():
    return StripeLegacyCustomerService()


@pytest.fixture
def charge_service():
    return StripeLegacyChargeService()


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

    def test_remove_source_calls_delete(self, customer_service, mocker):
        mock_source = mocker.MagicMock()
        customer_service.remove_source(mock_source)
        mock_source.delete.assert_called_once()

    def test_get_card_returns_card_source(self, customer_service, mocker):
        mock_source = mocker.MagicMock(object="card")
        mock_customer = mocker.MagicMock()
        mock_customer.default_source = "card_123"
        mock_customer.sources.retrieve.return_value = mock_source
        result = customer_service.get_card(mock_customer)
        mock_customer.sources.retrieve.assert_called_once_with("card_123")
        assert result == mock_source

    def test_get_card_returns_none_for_non_card_source(
        self, customer_service, mocker
    ):
        mock_source = mocker.MagicMock(object="ach_debit")
        mock_customer = mocker.MagicMock()
        mock_customer.default_source = "src_123"
        mock_customer.sources.retrieve.return_value = mock_source
        result = customer_service.get_card(mock_customer)
        assert result is None

    def test_get_card_returns_none_when_no_default_source(
        self, customer_service, mocker
    ):
        mock_customer = mocker.MagicMock()
        mock_customer.default_source = None
        result = customer_service.get_card(mock_customer)
        assert result is None


class TestLegacyChargeService:
    def test_confirm_payment_intent_raises_not_implemented(self, charge_service):
        with pytest.raises(NotImplementedError):
            charge_service.confirm_payment_intent("pi_123")


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
