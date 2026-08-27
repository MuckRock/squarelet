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
