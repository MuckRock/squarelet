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

    @pytest.mark.django_db()
    def test_make_charge_with_new_card_token(self, mocker):
        """Test creating charge with new card token"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_test123")
        token = "tok_visa"

        # Mock at provider service level
        mock_source = mocker.Mock(id="src_123")
        mock_source.delete = mocker.Mock()
        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_test123", created=timestamp)

        mocker.patch(
            "squarelet.organizations.models.Customer.add_source",
            return_value=mock_source,
        )
        mocker.patch("squarelet.organizations.models.Customer.stripe_customer")
        mock_charge_create = mocker.patch(
            "squarelet.organizations.querysets.get_payment_provider"
        ).return_value.get_charge_service.return_value.create
        mock_charge_create.return_value = mock_stripe_charge

        # Act
        charge = Charge.objects.make_charge(
            organization=org,
            token=token,
            amount=5000,
            fee_amount=100,
            description="Test charge",
            metadata={"test": "value"},
        )

        # Assert model-level behavior
        mock_source.delete.assert_called_once()
        assert charge.charge_id == "ch_test123"
        assert charge.organization == org

    @pytest.mark.django_db()
    def test_make_charge_with_saved_card(self, mocker):
        """Test creating charge with saved card (no token)"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_saved")

        # Mock Stripe customer with saved card
        mock_card = mocker.Mock(id="card_123")
        mock_stripe_customer = mocker.Mock()
        mock_stripe_customer.sources = mocker.Mock()
        mock_stripe_customer.sources.data = [mock_card]
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Customer.retrieve",
            return_value=mock_stripe_customer,
        )

        # Mock Customer.card property to return the mock card
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card",
            new_callable=mocker.PropertyMock,
            return_value=mock_card,
        )

        # Mock charge creation
        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_saved_card", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=3000,
            fee_amount=0,
            description="Saved card charge",
            metadata={},
        )

        # Assert
        mock_charge_create.assert_called_once()
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["source"] == mock_card
        assert charge.charge_id == "ch_saved_card"

    def _mock_customer_with_card(self, mocker):
        """Helper to mock Stripe customer with saved card"""
        mock_card = mocker.Mock(id="card_123")
        mock_stripe_customer = mocker.Mock()
        mock_stripe_customer.sources = mocker.Mock()
        mock_stripe_customer.sources.data = [mock_card]
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Customer.retrieve",
            return_value=mock_stripe_customer,
        )
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card",
            new_callable=mocker.PropertyMock,
            return_value=mock_card,
        )
        return mock_card

    @pytest.mark.django_db()
    def test_make_charge_includes_default_metadata(self, mocker):
        """Test charge includes organization metadata"""
        # Arrange
        org = OrganizationFactory(name="Test Org", customer__customer_id="cus_meta")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_metadata", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=50,
            description="Metadata test",
            metadata={},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["organization"] == "Test Org"
        assert metadata["organization id"] == str(org.uuid)
        assert metadata["fee amount"] == 50

    @pytest.mark.django_db()
    def test_make_charge_merges_custom_metadata(self, mocker):
        """Test custom metadata is merged with defaults"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_custom")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_custom", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=2000,
            fee_amount=0,
            description="Custom metadata",
            metadata={"custom_field": "custom_value", "action": "test-action"},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["custom_field"] == "custom_value"
        assert metadata["action"] == "test-action"
        assert metadata["organization"] == org.name  # Default still included

    @pytest.mark.django_db()
    def test_make_charge_uses_idempotency_key(self, mocker):
        """Test idempotency key is UUID"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_idem")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_idempotent", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1500,
            fee_amount=0,
            description="Idempotency test",
            metadata={},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        idempotency_key = call_kwargs["idempotency_key"]
        assert isinstance(idempotency_key, str)
        assert len(idempotency_key) > 0
        # UUID4 format check (simple validation)
        assert "-" in idempotency_key

    @pytest.mark.django_db()
    def test_make_charge_statement_descriptor_from_metadata(self, mocker):
        """Test statement descriptor from metadata action"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_desc")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_descriptor", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=2500,
            fee_amount=0,
            description="Descriptor test",
            metadata={"action": "Request Filing"},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["statement_descriptor_suffix"] == "Request Filing"

    @pytest.mark.django_db()
    def test_make_charge_statement_descriptor_empty_when_no_action(self, mocker):
        """Test statement descriptor empty when no action in metadata"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_noact")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_no_action", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=0,
            description="No action test",
            metadata={},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["statement_descriptor_suffix"] == ""

    @pytest.mark.django_db()
    def test_make_charge_race_condition_with_webhook(self, mocker):
        """Test get_or_create handles webhook race condition"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_race")
        self._mock_customer_with_card(mocker)

        # Create existing charge (simulating webhook creating it first)
        existing_charge = ChargeFactory(charge_id="ch_existing", organization=org)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_existing", created=timestamp)
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=5000,
            fee_amount=0,
            description="Race test",
            metadata={},
        )

        # Assert
        assert charge.id == existing_charge.id  # Same database record
        assert (
            Charge.objects.filter(charge_id="ch_existing").count() == 1
        )  # No duplicate

    @pytest.mark.django_db()
    def test_make_charge_with_zero_fee_amount(self, mocker):
        """Test charge with zero fee amount"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_zero")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_zero_fee", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        # Act
        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=1000,
            fee_amount=0,
            description="Zero fee test",
            metadata={},
        )

        # Assert
        assert charge.fee_amount == 0
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["metadata"]["fee amount"] == 0

    @pytest.mark.django_db()
    def test_make_charge_stripe_card_error(self, mocker):
        """Test handling of Stripe card errors"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_card_err")
        self._mock_customer_with_card(mocker)

        # Mock Stripe to raise CardError
        card_error = stripe.CardError(
            message="Your card was declined",
            param="card",
            code="card_declined",
        )
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            side_effect=card_error,
        )

        # Act & Assert
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
        # Verify no Charge record was created
        assert not Charge.objects.filter(organization=org).exists()

    @pytest.mark.django_db()
    def test_make_charge_stripe_api_error(self, mocker):
        """Test handling of Stripe API errors"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_api_err")
        self._mock_customer_with_card(mocker)

        # Mock Stripe to raise APIError
        api_error = stripe.APIError(
            message="An error occurred with our API",
        )
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            side_effect=api_error,
        )

        # Act & Assert
        with pytest.raises(stripe.APIError):
            Charge.objects.make_charge(
                organization=org,
                token=None,
                amount=2000,
                fee_amount=0,
                description="API error test",
                metadata={},
            )

        # Verify no Charge record was created
        assert not Charge.objects.filter(organization=org).exists()

    @pytest.mark.django_db()
    def test_make_charge_customer_without_card(self, mocker):
        """Test error when customer has no saved card"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_no_card")

        # Mock Stripe customer WITHOUT saved card
        mock_stripe_customer = mocker.Mock()
        mock_stripe_customer.sources = mocker.Mock()
        mock_stripe_customer.sources.data = []  # No cards saved
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Customer.retrieve",
            return_value=mock_stripe_customer,
        )

        # Mock Customer.card property to return None (no card)
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card",
            new_callable=mocker.PropertyMock,
            return_value=None,
        )

        # Mock charge creation to raise error
        invalid_error = stripe.InvalidRequestError(
            message="Cannot charge a customer that has no active card",
            param="source",
        )
        mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            side_effect=invalid_error,
        )

        # Act & Assert
        with pytest.raises(stripe.InvalidRequestError):
            Charge.objects.make_charge(
                organization=org,
                token=None,  # No token provided
                amount=1000,
                fee_amount=0,
                description="No card test",
                metadata={},
            )

    @pytest.mark.django_db()
    def test_make_charge_large_amount(self, mocker):
        """Test charge with large amount"""
        # Arrange
        org = OrganizationFactory(customer__customer_id="cus_large")
        self._mock_customer_with_card(mocker)

        timestamp = int(timezone.now().timestamp())
        mock_stripe_charge = mocker.Mock(id="ch_large", created=timestamp)
        mock_charge_create = mocker.patch(
            "squarelet.organizations.payments.providers"
            ".stripe_legacy.stripe.Charge.create",
            return_value=mock_stripe_charge,
        )

        large_amount = 100000  # $1,000.00 in cents (reasonable large amount)
        charge = Charge.objects.make_charge(
            organization=org,
            token=None,
            amount=large_amount,
            fee_amount=5000,  # $50 fee (within smallint range)
            description="Large amount test",
            metadata={},
        )

        # Assert
        call_kwargs = mock_charge_create.call_args[1]
        assert call_kwargs["amount"] == large_amount
        assert charge.amount == large_amount
        assert charge.fee_amount == 5000
