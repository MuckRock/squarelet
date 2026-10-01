# The command's per-price step is the unit under test here.
# pylint: disable=protected-access

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.management.commands.consolidate_stripe_products import (
    PRICE_MATRIX,
    Command,
)
from squarelet.organizations.models import PlanPrice


@pytest.mark.django_db()
class TestCreatingAPrice:
    def test_a_stripe_failure_leaves_no_row(self, plan_factory, mocker):
        """A paid row without a Stripe Price would sell at the legacy plan."""
        plan = plan_factory(name="Paid Plan", base_price=100)
        mocker.patch(
            "squarelet.organizations.models.Plan.ensure_stripe_product",
            return_value="prod_test",
        )
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_plan_service.return_value
        service.find_price.return_value = None
        service.create_price.side_effect = stripe.APIConnectionError("down")

        with pytest.raises(stripe.APIConnectionError):
            Command()._ensure_price(
                plan, ("monthly", "standard", "", 1_000), dry_run=False
            )

        assert not PlanPrice.objects.filter(plan=plan).exists()


@pytest.mark.django_db()
class TestTheMatrix:
    def test_a_price_without_an_amount_waits(self, plan_factory, mocker):
        """Until the amount is decided, no row and no Stripe Price."""
        plan = plan_factory(name="Pending Plan", base_price=100)
        create = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_plan_service.return_value.create_price

        result = Command()._ensure_price(
            plan, ("monthly", "nonprofit", "", None), dry_run=False
        )

        assert result == "pending"
        assert not PlanPrice.objects.filter(plan=plan).exists()
        create.assert_not_called()

    def test_a_price_set_by_hand_is_reported_as_there(
        self, plan_factory, plan_price_factory
    ):
        """So the report matches what purchases can already see."""
        plan = plan_factory(name="Pending Plan", base_price=100)
        plan_price_factory(plan=plan, interval="monthly", label="nonprofit")

        result = Command()._ensure_price(
            plan, ("monthly", "nonprofit", "", None), dry_run=False
        )

        assert result == "skipped"

    def test_the_cohort_rate_is_one_deal_at_both_cadences(self):
        cohort = {
            interval: amount
            for slug, interval, label, code, amount in PRICE_MATRIX
            if code == "election-cohort"
        }

        assert cohort["monthly"] * 12 == cohort["annual"]
