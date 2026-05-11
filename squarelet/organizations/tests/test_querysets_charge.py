# Django
from django.utils import timezone

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import Charge
from squarelet.organizations.tests.factories import ChargeFactory, OrganizationFactory


class TestChargeQuerySet:
    """Unit tests for ChargeQuerySet.make_charge()"""

    def _mock_provider_charge(self, mocker, charge_id="ch_test", created=None):
        """Return a mock charge and the provider create mock."""
        if created is None:
            created = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id=charge_id, created=created)
        mock_provider = mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value
        mock_provider.get_charge_service.return_value.create.return_value = (
            mock_stripe_charge
        )
        return mock_stripe_charge, mock_provider

    def _mock_customer_with_card(self, mocker):
        """Mock Customer.card and stripe_customer for saved-card tests."""
        mock_card = mocker.Mock(id="card_123")
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card",
            new_callable=mocker.PropertyMock,
            return_value=mock_card,
        )
        mocker.patch("squarelet.organizations.models.Customer.stripe_customer")
        return mock_card

    @pytest.mark.django_db()
    def test_make_charge_with_new_card_token(self, mocker):
        """Test creating charge with new card token"""
        org = OrganizationFactory(customer__customer_id="cus_test123")
        token = "tok_visa"

        mock_source = mocker.Mock(id="pm_123")
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_test123"
        )
        mocker.patch(
            "squarelet.organizations.models.Customer.add_source",
            return_value=mock_source,
        )
        mocker.patch("squarelet.organizations.models.Customer.stripe_customer")
        mock_remove_source = (
            mock_provider.get_customer_service.return_value.remove_source
        )

        charge = Charge.objects.make_charge(
            organization=org,
            token=token,
            amount=5000,
            fee_amount=100,
            description="Test charge",
            metadata={"test": "value"},
        )

        mock_remove_source.assert_called_once_with(mock_source)
        assert charge.charge_id == "ch_test123"
        assert charge.organization == org

    @pytest.mark.django_db()
    def test_make_charge_with_saved_card(self, mocker):
        """Test creating charge with saved card (no token)"""
        org = OrganizationFactory(customer__customer_id="cus_saved")
        mock_card = self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_saved_card"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=3000,
            fee_amount=0,
            description="Saved card charge",
            metadata={},
        )

        mock_charge_create.assert_called_once()
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["source"] == mock_card
        assert charge.charge_id == "ch_saved_card"

    @pytest.mark.django_db()
    def test_make_charge_includes_default_metadata(self, mocker):
        """Test charge includes organization metadata"""
        org = OrganizationFactory(name="Test Org", customer__customer_id="cus_meta")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_metadata"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=50,
            description="Metadata test",
            metadata={},
        )

        call_kwargs = mock_charge_create.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["organization"] == "Test Org"
        assert metadata["organization id"] == str(org.uuid)
        assert metadata["fee amount"] == 50

    @pytest.mark.django_db()
    def test_make_charge_merges_custom_metadata(self, mocker):
        """Test custom metadata is merged with defaults"""
        org = OrganizationFactory(customer__customer_id="cus_custom")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_custom"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=2000,
            fee_amount=0,
            description="Custom metadata",
            metadata={"custom_field": "custom_value", "action": "test-action"},
        )

        call_kwargs = mock_charge_create.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["custom_field"] == "custom_value"
        assert metadata["action"] == "test-action"
        assert metadata["organization"] == org.name

    @pytest.mark.django_db()
    def test_make_charge_uses_idempotency_key(self, mocker):
        """Test idempotency key is UUID"""
        org = OrganizationFactory(customer__customer_id="cus_idem")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_idempotent"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1500,
            fee_amount=0,
            description="Idempotency test",
            metadata={},
        )

        call_kwargs = mock_charge_create.call_args[1]
        idempotency_key = call_kwargs["idempotency_key"]
        assert isinstance(idempotency_key, str)
        assert len(idempotency_key) > 0
        assert "-" in idempotency_key

    @pytest.mark.django_db()
    def test_make_charge_statement_descriptor_from_metadata(self, mocker):
        """Test statement descriptor from metadata action"""
        org = OrganizationFactory(customer__customer_id="cus_desc")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_descriptor"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=2500,
            fee_amount=0,
            description="Descriptor test",
            metadata={"action": "Request Filing"},
        )

        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["statement_descriptor_suffix"] == "Request Filing"

    @pytest.mark.django_db()
    def test_make_charge_statement_descriptor_empty_when_no_action(self, mocker):
        """Test statement descriptor empty when no action in metadata"""
        org = OrganizationFactory(customer__customer_id="cus_noact")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_no_action"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=0,
            description="No action test",
            metadata={},
        )

        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["statement_descriptor_suffix"] == ""

    @pytest.mark.django_db()
    def test_make_charge_race_condition_with_webhook(self, mocker):
        """Test get_or_create handles webhook race condition"""
        org = OrganizationFactory(customer__customer_id="cus_race")
        self._mock_customer_with_card(mocker)

        existing_charge = ChargeFactory(charge_id="ch_existing", organization=org)

        mock_stripe_charge, _ = self._mock_provider_charge(mocker, "ch_existing")

        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=5000,
            fee_amount=0,
            description="Race test",
            metadata={},
        )

        assert charge.id == existing_charge.id
        assert Charge.objects.filter(charge_id="ch_existing").count() == 1

    @pytest.mark.django_db()
    def test_make_charge_with_zero_fee_amount(self, mocker):
        """Test charge with zero fee amount"""
        org = OrganizationFactory(customer__customer_id="cus_zero")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_zero_fee"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=0,
            description="Zero fee test",
            metadata={},
        )

        assert charge.fee_amount == 0
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["metadata"]["fee amount"] == 0

    @pytest.mark.django_db()
    def test_make_charge_stripe_card_error(self, mocker):
        """Test handling of Stripe card errors"""
        org = OrganizationFactory(customer__customer_id="cus_card_err")
        self._mock_customer_with_card(mocker)

        card_error = stripe.CardError(
            message="Your card was declined",
            param="card",
            code="card_declined",
        )
        mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value.get_charge_service.return_value.create.side_effect = card_error

        with pytest.raises(stripe.CardError) as exc_info:
            Charge.objects.make_charge(
                organization=org,
                token=None,
                amount=1000,
                fee_amount=0,
                description="Card error test",
                metadata={},
            )

        assert exc_info.value.code == "card_declined"
        assert not Charge.objects.filter(organization=org).exists()

    @pytest.mark.django_db()
    def test_make_charge_stripe_api_error(self, mocker):
        """Test handling of Stripe API errors"""
        org = OrganizationFactory(customer__customer_id="cus_api_err")
        self._mock_customer_with_card(mocker)

        api_error = stripe.APIError(message="An error occurred with our API")
        mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value.get_charge_service.return_value.create.side_effect = api_error

        with pytest.raises(stripe.APIError):
            Charge.objects.make_charge(
                organization=org,
                token=None,
                amount=2000,
                fee_amount=0,
                description="API error test",
                metadata={},
            )

        assert not Charge.objects.filter(organization=org).exists()

    @pytest.mark.django_db()
    def test_make_charge_customer_without_card(self, mocker):
        """Test error when customer has no saved card"""
        org = OrganizationFactory(customer__customer_id="cus_no_card")
        mocker.patch("squarelet.organizations.models.Customer.stripe_customer")
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card",
            new_callable=mocker.PropertyMock,
            return_value=None,
        )

        invalid_error = stripe.InvalidRequestError(
            message="Cannot charge a customer that has no active card",
            param="source",
        )
        mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value.get_charge_service.return_value.create.side_effect = (
            invalid_error
        )

        with pytest.raises(stripe.InvalidRequestError):
            Charge.objects.make_charge(
                organization=org,
                token=None,
                amount=1000,
                fee_amount=0,
                description="No card test",
                metadata={},
            )

    @pytest.mark.django_db()
    def test_make_charge_large_amount(self, mocker):
        """Test charge with large amount"""
        org = OrganizationFactory(customer__customer_id="cus_large")
        self._mock_customer_with_card(mocker)
        mock_stripe_charge, mock_provider = self._mock_provider_charge(
            mocker, "ch_large"
        )
        mock_charge_create = mock_provider.get_charge_service.return_value.create

        large_amount = 100000
        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=large_amount,
            fee_amount=5000,
            description="Large amount test",
            metadata={},
        )

        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["amount"] == large_amount
        assert charge.amount == large_amount
        assert charge.fee_amount == 5000


class TestConfirmPaymentIntent:
    """Unit tests for ChargeQuerySet.confirm_payment_intent()"""

    def _mock_provider_confirm(self, mocker, charge_id="ch_confirmed", pm_id="pm_123"):
        """Return a mock (charge, pm_id) result and the provider confirm mock."""
        import time
        mock_stripe_charge = mocker.Mock(id=charge_id, created=int(time.time()))
        mock_provider = mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value
        mock_provider.get_charge_service.return_value.confirm_payment_intent.return_value = (
            mock_stripe_charge,
            pm_id,
        )
        return mock_stripe_charge, mock_provider

    @pytest.mark.django_db()
    def test_confirm_creates_charge(self, mocker):
        """Test that confirm_payment_intent creates a local Charge record."""
        from squarelet.organizations.tests.factories import OrganizationFactory
        org = OrganizationFactory()
        mock_stripe_charge, mock_provider = self._mock_provider_confirm(
            mocker, "ch_confirmed"
        )

        charge = Charge.objects.confirm_payment_intent(
            payment_intent_id="pi_123",
            organization=org,
            amount=2000,
            fee_amount=50,
            description="Test confirm",
            metadata={},
            save_card=False,
        )

        assert charge.charge_id == "ch_confirmed"
        assert charge.amount == 2000
        assert charge.organization == org

    @pytest.mark.django_db()
    def test_confirm_detaches_temp_pm_when_not_saving_card(self, mocker):
        """Temporary PM is removed after confirm when save_card=False."""
        from squarelet.organizations.tests.factories import OrganizationFactory
        org = OrganizationFactory()
        mock_stripe_charge, mock_provider = self._mock_provider_confirm(
            mocker, "ch_no_save", pm_id="pm_temp"
        )
        mock_remove_source = mock_provider.get_customer_service.return_value.remove_source

        Charge.objects.confirm_payment_intent(
            payment_intent_id="pi_123",
            organization=org,
            amount=1000,
            fee_amount=0,
            description="No save",
            metadata={},
            save_card=False,
        )

        mock_remove_source.assert_called_once_with("pm_temp")

    @pytest.mark.django_db()
    def test_confirm_does_not_detach_pm_when_saving_card(self, mocker):
        """Saved card PM is not removed after confirm when save_card=True."""
        from squarelet.organizations.tests.factories import OrganizationFactory
        org = OrganizationFactory()
        mock_stripe_charge, mock_provider = self._mock_provider_confirm(
            mocker, "ch_with_save", pm_id="pm_saved"
        )
        mock_remove_source = mock_provider.get_customer_service.return_value.remove_source

        Charge.objects.confirm_payment_intent(
            payment_intent_id="pi_123",
            organization=org,
            amount=1000,
            fee_amount=0,
            description="Save card",
            metadata={},
            save_card=True,
        )

        mock_remove_source.assert_not_called()

    @pytest.mark.django_db()
    def test_confirm_race_condition_with_webhook(self, mocker):
        """get_or_create handles webhook race on confirm path."""
        from squarelet.organizations.tests.factories import ChargeFactory, OrganizationFactory
        org = OrganizationFactory()
        existing_charge = ChargeFactory(charge_id="ch_existing_confirm", organization=org)
        mock_stripe_charge, _ = self._mock_provider_confirm(
            mocker, "ch_existing_confirm", pm_id=None
        )
        # pm_id=None → no remove_source call expected
        charge = Charge.objects.confirm_payment_intent(
            payment_intent_id="pi_race",
            organization=org,
            amount=5000,
            fee_amount=0,
            description="Race confirm",
            metadata={},
            save_card=False,
        )
        assert charge.id == existing_charge.id
        assert Charge.objects.filter(charge_id="ch_existing_confirm").count() == 1
