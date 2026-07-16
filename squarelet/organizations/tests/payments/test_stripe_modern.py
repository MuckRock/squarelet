# Third Party
import pytest

# Squarelet
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.providers.stripe_modern import (
    StripeModernChargeService,
    StripeModernCustomerService,
    StripeModernSubscriptionService,
)

# pylint: disable=redefined-outer-name


@pytest.fixture
def customer_service():
    return StripeModernCustomerService()


@pytest.fixture
def subscription_service():
    return StripeModernSubscriptionService()


@pytest.fixture
def charge_service():
    return StripeModernChargeService()


class TestModernCustomerService:
    def test_retrieve_source(self, customer_service, mocker):
        customer_id = "cus_123"
        source_id = "src_123"
        mock_retrieve = mocker.patch("stripe.Customer.retrieve_source")
        result = customer_service.retrieve_source(customer_id, source_id)
        mock_retrieve.assert_called_once_with(customer_id, source_id)
        assert result == mock_retrieve.return_value

    def test_add_source_creates_and_attaches_payment_method(
        self, customer_service, mocker
    ):
        customer_id = "cus_123"
        token = "tok_123"
        mock_customer = mocker.MagicMock(id=customer_id)
        mock_pm = mocker.MagicMock(id="pm_123")
        mock_create = mocker.patch("stripe.PaymentMethod.create", return_value=mock_pm)
        mock_attach = mocker.patch("stripe.PaymentMethod.attach")
        result = customer_service.add_source(mock_customer, token)
        mock_create.assert_called_once_with(type="card", card={"token": token})
        mock_attach.assert_called_once_with("pm_123", customer=customer_id)
        assert result == mock_pm

    def test_remove_source_detaches_payment_method(self, customer_service, mocker):
        mock_pm = mocker.MagicMock(id="pm_123")
        mock_detach = mocker.patch("stripe.PaymentMethod.detach")
        customer_service.remove_source(mock_pm)
        mock_detach.assert_called_once_with("pm_123")

    def test_remove_source_accepts_string_id(self, customer_service, mocker):
        mock_detach = mocker.patch("stripe.PaymentMethod.detach")
        customer_service.remove_source("pm_456")
        mock_detach.assert_called_once_with("pm_456")

    def test_save_card_creates_attaches_and_sets_default(
        self, customer_service, mocker
    ):
        customer_id = "cus_123"
        token = "tok_123"
        mock_customer = mocker.MagicMock(id=customer_id)
        mock_pm = mocker.MagicMock(id="pm_new")
        mock_create = mocker.patch("stripe.PaymentMethod.create", return_value=mock_pm)
        mock_attach = mocker.patch("stripe.PaymentMethod.attach")
        mock_modify = mocker.patch("stripe.Customer.modify")
        customer_service.save_card(mock_customer, token)
        mock_create.assert_called_once_with(type="card", card={"token": token})
        mock_attach.assert_called_once_with("pm_new", customer=customer_id)
        mock_modify.assert_called_once_with(
            customer_id,
            invoice_settings={"default_payment_method": "pm_new"},
        )

    def test_remove_payment_method_detaches_payment_method(
        self, customer_service, mocker
    ):
        mock_detach = mocker.patch("stripe.PaymentMethod.detach")
        mock_modify = mocker.patch("stripe.Customer.modify")
        customer_service.remove_payment_method("cus_123", "pm_abc")
        mock_detach.assert_called_once_with("pm_abc")
        mock_modify.assert_called_once_with(
            "cus_123", invoice_settings={"default_payment_method": ""}
        )

    def test_remove_payment_method_deletes_legacy_source(
        self, customer_service, mocker
    ):
        mock_delete = mocker.patch("stripe.Customer.delete_source")
        customer_service.remove_payment_method("cus_123", "card_abc")
        mock_delete.assert_called_once_with("cus_123", "card_abc")

    def test_get_payment_method_returns_default_payment_method(
        self, customer_service, mocker
    ):
        pm_id = "pm_123"
        mock_pm = mocker.MagicMock(id=pm_id, object="payment_method")
        mock_customer = mocker.MagicMock()
        mock_customer.invoice_settings.default_payment_method = pm_id
        mock_customer.default_source = None
        mock_retrieve = mocker.patch(
            "stripe.PaymentMethod.retrieve", return_value=mock_pm
        )
        result = customer_service.get_payment_method(mock_customer)
        mock_retrieve.assert_called_once_with(pm_id)
        assert result == mock_pm

    def test_get_payment_method_falls_back_to_source(self, customer_service, mocker):
        mock_source = mocker.MagicMock(id="card_123", object="card")
        mock_customer = mocker.MagicMock()
        mock_customer.invoice_settings.default_payment_method = None
        mock_customer.default_source = "card_123"
        mock_retrieve = mocker.patch(
            "stripe.Customer.retrieve_source", return_value=mock_source
        )
        result = customer_service.get_payment_method(mock_customer)
        mock_retrieve.assert_called_once_with(mock_customer.id, "card_123")
        assert result == mock_source

    def test_get_payment_method_returns_none_when_no_saved_card(
        self, customer_service, mocker
    ):
        mock_customer = mocker.MagicMock()
        mock_customer.invoice_settings.default_payment_method = None
        mock_customer.default_source = None
        result = customer_service.get_payment_method(mock_customer)
        assert result is None

    def test_get_payment_method_returns_none_for_non_card_source(
        self, customer_service, mocker
    ):
        mock_source = mocker.MagicMock(id="src_123", object="ach_debit")
        mock_customer = mocker.MagicMock()
        mock_customer.invoice_settings.default_payment_method = None
        mock_customer.default_source = "src_123"
        mocker.patch("stripe.Customer.retrieve_source", return_value=mock_source)
        result = customer_service.get_payment_method(mock_customer)
        assert result is None


class TestModernChargeService:
    def test_create_uses_payment_intent(self, charge_service, mocker):
        mock_source = mocker.MagicMock(id="pm_123")
        mock_customer = mocker.MagicMock(id="cus_123")
        mock_charge = mocker.MagicMock(id="ch_123", created=1700000000)
        mock_intent = mocker.MagicMock(latest_charge=mock_charge, status="succeeded")
        mock_create = mocker.patch(
            "stripe.PaymentIntent.create", return_value=mock_intent
        )
        result = charge_service.create(
            amount=1000,
            currency="usd",
            customer=mock_customer,
            description="Test",
            source=mock_source,
            metadata={"key": "val"},
            statement_descriptor_suffix="Test",
            idempotency_key="idem-123",
        )
        mock_create.assert_called_once_with(
            amount=1000,
            currency="usd",
            customer="cus_123",
            payment_method="pm_123",
            description="Test",
            metadata={"key": "val"},
            statement_descriptor_suffix="Test",
            confirm=True,
            automatic_payment_methods={
                "enabled": True,
                "allow_redirects": "never",
            },
            expand=["latest_charge"],
            idempotency_key="idem-123",
        )
        assert result == mock_charge

    def test_create_raises_payment_action_required_for_3ds(
        self, charge_service, mocker
    ):
        """When Stripe requires 3DS, PaymentActionRequired is raised."""
        mock_source = mocker.MagicMock(id="pm_123")
        mock_customer = mocker.MagicMock(id="cus_123")
        mock_intent = mocker.MagicMock(
            status="requires_action",
            client_secret="pi_secret",
            id="pi_123",
        )
        mocker.patch("stripe.PaymentIntent.create", return_value=mock_intent)
        with pytest.raises(PaymentActionRequired) as exc_info:
            charge_service.create(
                amount=1000,
                currency="usd",
                customer=mock_customer,
                description="Test",
                source=mock_source,
                metadata={},
                statement_descriptor_suffix="",
                idempotency_key="idem-123",
            )
        assert exc_info.value.client_secret == "pi_secret"
        assert exc_info.value.payment_intent_id == "pi_123"

    def test_create_works_with_legacy_source_id(self, charge_service, mocker):
        """Card/Source objects saved before migration still work as payment_method."""
        mock_source = mocker.MagicMock(id="card_abc")
        mock_customer = mocker.MagicMock(id="cus_123")
        mock_charge = mocker.MagicMock(id="ch_456")
        mock_intent = mocker.MagicMock(latest_charge=mock_charge, status="succeeded")
        mock_create = mocker.patch(
            "stripe.PaymentIntent.create", return_value=mock_intent
        )
        result = charge_service.create(
            amount=500,
            currency="usd",
            customer=mock_customer,
            description="Legacy",
            source=mock_source,
            metadata={},
            statement_descriptor_suffix="",
            idempotency_key="idem-456",
        )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["payment_method"] == "card_abc"
        assert "off_session" not in call_kwargs
        assert result == mock_charge

    def test_confirm_payment_intent_returns_charge_and_pm_id(
        self, charge_service, mocker
    ):
        mock_charge = mocker.MagicMock(id="ch_123")
        mock_intent = mocker.MagicMock(
            status="succeeded",
            latest_charge=mock_charge,
            payment_method="pm_123",
        )
        mock_retrieve = mocker.patch(
            "stripe.PaymentIntent.retrieve", return_value=mock_intent
        )
        charge, pm_id = charge_service.confirm_payment_intent("pi_123")
        mock_retrieve.assert_called_once_with("pi_123", expand=["latest_charge"])
        assert charge == mock_charge
        assert pm_id == "pm_123"

    def test_confirm_payment_intent_raises_on_non_succeeded(
        self, charge_service, mocker
    ):
        mock_intent = mocker.MagicMock(status="requires_action")
        mocker.patch("stripe.PaymentIntent.retrieve", return_value=mock_intent)
        with pytest.raises(ValueError, match="requires_action"):
            charge_service.confirm_payment_intent("pi_123")

    def test_retrieve_uses_charge_api(self, charge_service, mocker):
        mock_retrieve = mocker.patch("stripe.Charge.retrieve")
        charge_service.retrieve("ch_123")
        mock_retrieve.assert_called_once_with("ch_123")


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
            cancel_at_period_end=False,
            expand=["latest_invoice.confirmation_secret"],
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
            cancel_at_period_end=False,
            expand=["latest_invoice.confirmation_secret"],
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

    def test_cancel_at_period_end_returns_updated_subscription(
        self, subscription_service, mocker
    ):
        mock_sub = mocker.MagicMock(id="sub_123")
        mock_updated = mocker.MagicMock(cancel_at=1_800_000_000)
        mock_modify = mocker.patch(
            "stripe.Subscription.modify", return_value=mock_updated
        )
        result = subscription_service.cancel_at_period_end(mock_sub)
        mock_modify.assert_called_once_with("sub_123", cancel_at_period_end=True)
        assert result is mock_updated

    def test_get_current_period_end(self, subscription_service, mocker):
        mock_item = mocker.MagicMock(current_period_end=1700000000)
        mock_sub = mocker.MagicMock()
        mock_sub.items.data = [mock_item]
        assert subscription_service.get_current_period_end(mock_sub) == 1700000000

    def test_get_current_period_end_no_items(self, subscription_service, mocker):
        mock_sub = mocker.MagicMock()
        mock_sub.items.data = []
        assert subscription_service.get_current_period_end(mock_sub) is None
