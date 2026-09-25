# The command's per-price step is the unit under test here.
# pylint: disable=protected-access

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.management.commands.consolidate_stripe_products import (
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
