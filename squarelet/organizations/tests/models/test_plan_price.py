# Django
from django.core.exceptions import ValidationError

# Standard Library
from unittest.mock import Mock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import PlanPrice


@pytest.fixture(name="plan_service")
def plan_service_fixture(mocker):
    """The Stripe plan service, with a product already in place."""
    service = mocker.patch(
        "squarelet.organizations.models.payment.get_payment_provider"
    ).return_value.get_plan_service.return_value
    service.find_product.return_value = None
    service.create_product.return_value = Mock(id="prod_test")
    service.find_price.return_value = None
    service.create_price.return_value = Mock(id="price_new")
    return service


@pytest.mark.django_db()
class TestEnsureStripePrice:
    def test_comped_price_never_reaches_stripe(self, plan_price_factory, plan_service):
        price = plan_price_factory(amount=0)

        assert price.ensure_stripe_price() is None
        plan_service.create_price.assert_not_called()
        assert price.stripe_price_id == ""

    def test_existing_price_is_left_alone(self, plan_price_factory, plan_service):
        price = plan_price_factory(stripe_price_id="price_already")

        assert price.ensure_stripe_price() == "price_already"
        plan_service.create_price.assert_not_called()

    def test_creates_and_records_a_price(self, plan_price_factory, plan_service):
        price = plan_price_factory()

        assert price.ensure_stripe_price() == "price_new"

        price.refresh_from_db()
        assert price.stripe_price_id == "price_new"
        kwargs = plan_service.create_price.call_args.kwargs
        assert kwargs["unit_amount"] == price.amount
        assert kwargs["metadata"]["squarelet_variant"] == price.variant_key

    def test_adopts_an_orphaned_price_instead_of_duplicating(
        self, plan_price_factory, plan_service
    ):
        """The case a rolled-back transaction leaves behind."""
        plan_service.find_price.return_value = Mock(id="price_orphan")
        price = plan_price_factory()

        assert price.ensure_stripe_price() == "price_orphan"

        plan_service.create_price.assert_not_called()
        price.refresh_from_db()
        assert price.stripe_price_id == "price_orphan"

    def test_lookup_uses_the_terms_not_the_primary_key(self, plan_price_factory):
        """A retry after a rollback has a different pk but the same terms."""
        first = plan_price_factory()
        key = first.variant_key
        first.delete()

        second = plan_price_factory(
            plan=first.plan,
            interval=first.interval,
            label=first.label,
            code=first.code,
            amount=first.amount,
        )

        assert second.pk != first.pk
        assert second.variant_key == key


@pytest.mark.django_db()
class TestSupersede:
    @pytest.mark.usefixtures("plan_service")
    def test_supersede_retires_and_replaces(self, plan_price_factory):
        original = plan_price_factory(amount=10000, code="negotiated")

        replacement = original.supersede(12000)

        original.refresh_from_db()
        assert not original.active
        assert replacement.active
        assert replacement.amount == 12000
        # A negotiated rate must supersede to another rate for the same deal
        assert replacement.code == "negotiated"
        assert replacement.stripe_price_id == "price_new"

    def test_cannot_supersede_twice(self, plan_price_factory):
        price = plan_price_factory(active=False)

        with pytest.raises(ValueError):
            price.supersede(12000)

    def test_stripe_failure_leaves_the_database_change_in_place(
        self, plan_price_factory, plan_service
    ):
        """The DB half is committed; the Stripe half is finished by retrying.

        The alternative - rolling the database back - would strand a Price
        that Stripe had already created and cannot undo.
        """
        plan_service.create_price.side_effect = ValueError("stripe is down")
        original = plan_price_factory(amount=10000)

        with pytest.raises(ValueError):
            original.supersede(12000)

        original.refresh_from_db()
        assert not original.active
        replacement = PlanPrice.objects.get(plan=original.plan, active=True)
        assert replacement.amount == 12000
        assert replacement.stripe_price_id == ""

        # Retrying finishes the job rather than making a second row
        plan_service.create_price.side_effect = None
        assert replacement.ensure_stripe_price() == "price_new"
        assert PlanPrice.objects.filter(plan=original.plan).count() == 2


@pytest.mark.django_db()
class TestEnsureStripeProduct:
    def test_adopts_an_orphaned_product(self, plan_factory, plan_service):
        """A Product left behind by a rolled-back request is reused."""
        plan_service.find_product.return_value = Mock(id="prod_orphan")
        plan = plan_factory()

        assert plan.ensure_stripe_product() == "prod_orphan"

        plan_service.create_product.assert_not_called()
        plan.refresh_from_db()
        assert plan.stripe_product_id == "prod_orphan"

    def test_creates_when_there_is_nothing_to_adopt(self, plan_factory, plan_service):
        plan = plan_factory()

        assert plan.ensure_stripe_product() == "prod_test"
        plan_service.create_product.assert_called_once()

    def test_existing_product_is_left_alone(self, plan_factory, plan_service):
        plan = plan_factory(stripe_product_id="prod_already")

        assert plan.ensure_stripe_product() == "prod_already"
        plan_service.find_product.assert_not_called()
        plan_service.create_product.assert_not_called()


@pytest.mark.django_db()
class TestPricedRowIsImmutable:
    """Stripe will not change a Price, so neither may we."""

    def test_amount_cannot_be_edited_once_priced(self, plan_price_factory):
        price = plan_price_factory(stripe_price_id="price_live", amount=10000)
        price.amount = 12000

        with pytest.raises(ValidationError) as excinfo:
            price.clean()
        assert "amount" in excinfo.value.message_dict

    def test_interval_and_currency_are_guarded_too(self, plan_price_factory):
        price = plan_price_factory(stripe_price_id="price_live")
        price.interval = "annual"
        price.currency = "eur"

        with pytest.raises(ValidationError) as excinfo:
            price.clean()
        assert set(excinfo.value.message_dict) == {"interval", "currency"}

    def test_classification_stays_editable(self, plan_price_factory):
        """label and code are local; they change nothing Stripe charges."""
        price = plan_price_factory(stripe_price_id="price_live")
        price.label = "nonprofit"
        price.code = "negotiated"

        price.clean()

    def test_a_row_with_no_stripe_price_is_free_to_change(self, plan_price_factory):
        price = plan_price_factory(amount=10000)
        price.amount = 12000

        price.clean()
