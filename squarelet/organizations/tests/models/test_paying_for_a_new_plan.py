"""What a card is charged at once for a plan, as the checkout page quotes it."""

# Standard Library
from datetime import date, datetime, timezone

# Third Party
import pytest
import stripe
from freezegun import freeze_time

# Squarelet
from squarelet.organizations.models import SubscriptionItem
from squarelet.organizations.querysets import next_billing_day


def line(amount, proration=True):
    details = {"proration": proration, "subscription_item": "si_new"}
    return {"amount": amount, "parent": {"subscription_item_details": details}}


@pytest.fixture(name="stripe_service")
def stripe_service_fixture(mocker):
    return mocker.patch(
        "squarelet.organizations.querysets.get_payment_provider"
    ).return_value.get_subscription_service.return_value


def due(organization, price):
    return SubscriptionItem.objects.due_on_start(organization, price)


@pytest.mark.django_db()
class TestWhatIsDueToday:
    def test_a_first_subscription_is_due_in_full_without_asking_stripe(
        self, organization_factory, plan_price_factory, stripe_service
    ):
        price = plan_price_factory(amount=4_000)

        assert due(organization_factory(), price) == 4_000
        stripe_service.preview_addition.assert_not_called()

    def test_joining_a_live_subscription_is_due_only_its_proration(
        self,
        organization_factory,
        plan_price_factory,
        subscription_factory,
        stripe_service,
    ):
        """The preview can carry the next period's charges; those aren't due now."""
        organization = organization_factory()
        subscription_factory(organization=organization, subscription_id="sub_live")
        price = plan_price_factory(amount=4_000)
        stripe_service.preview_addition.return_value = {
            "lines": {"data": [line(1_300), line(4_000, proration=False)]}
        }

        assert due(organization, price) == 1_300
        stripe_service.preview_addition.assert_called_once_with(
            organization.customer().customer_id,
            price.stripe_price_id,
            subscription_id="sub_live",
            anchor=None,
        )

    def test_a_cancelling_subscription_is_not_joined(
        self,
        organization_factory,
        plan_price_factory,
        subscription_factory,
        stripe_service,
    ):
        organization = organization_factory()
        subscription_factory(
            organization=organization, subscription_id="sub_ending", cancelled=True
        )

        assert due(organization, plan_price_factory(amount=4_000)) == 4_000
        stripe_service.preview_addition.assert_not_called()

    def test_an_annual_price_does_not_join_a_monthly_subscription(
        self,
        organization_factory,
        plan_price_factory,
        subscription_factory,
        stripe_service,
    ):
        organization = organization_factory()
        subscription_factory(organization=organization, subscription_id="sub_monthly")
        price = plan_price_factory(interval="annual", amount=40_000)

        assert due(organization, price) == 40_000
        stripe_service.preview_addition.assert_not_called()

    @freeze_time("2026-10-16 15:30:00")
    def test_a_new_monthly_subscription_is_prorated_to_the_billing_day(
        self, organization_factory, plan_price_factory, stripe_service
    ):
        organization = organization_factory(billing_anchor=date(2026, 3, 4))
        stripe_service.preview_addition.return_value = {"lines": {"data": [line(700)]}}

        assert due(organization, plan_price_factory(amount=4_000)) == 700
        anchor = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc).timestamp()
        assert stripe_service.preview_addition.call_args.kwargs == {
            "subscription_id": None,
            "anchor": int(anchor),
        }

    def test_nothing_is_quoted_when_stripe_does_not_answer(
        self,
        organization_factory,
        plan_price_factory,
        subscription_factory,
        stripe_service,
    ):
        organization = organization_factory()
        subscription_factory(organization=organization, subscription_id="sub_live")
        stripe_service.preview_addition.side_effect = stripe.APIConnectionError("down")

        assert due(organization, plan_price_factory(amount=4_000)) is None

    def test_a_free_price_is_due_nothing(
        self, organization_factory, plan_price_factory, stripe_service
    ):
        assert due(organization_factory(), plan_price_factory(amount=0)) == 0
        stripe_service.preview_addition.assert_not_called()


class TestTheNextBillingDay:
    def test_a_day_still_to_come_is_this_month(self):
        now = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)

        assert next_billing_day(20, now) == datetime(
            2026, 10, 20, 9, tzinfo=timezone.utc
        )

    def test_today_is_a_month_away(self):
        now = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)

        assert next_billing_day(16, now) == datetime(
            2026, 11, 16, 9, tzinfo=timezone.utc
        )

    def test_a_short_month_bills_on_its_last_day(self):
        now = datetime(2027, 2, 1, tzinfo=timezone.utc)

        assert next_billing_day(31, now) == datetime(2027, 2, 28, tzinfo=timezone.utc)

    def test_december_rolls_into_the_new_year(self):
        now = datetime(2026, 12, 20, tzinfo=timezone.utc)

        assert next_billing_day(5, now) == datetime(2027, 1, 5, tzinfo=timezone.utc)
