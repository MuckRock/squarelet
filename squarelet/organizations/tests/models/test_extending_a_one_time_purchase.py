"""A customer runs a one-time purchase for one more term, paid at renewal."""

# A fixture and the parameter that receives it necessarily share a name.
# pylint: disable=redefined-outer-name

# Django
from django.core.exceptions import ValidationError

# Standard Library
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import MagicMock, Mock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.payments.exceptions import SubscriptionError

# Noon UTC: Jan 31 2027, Feb 28 2027, Mar 31 2027 and Feb 28 2028.
JAN_31 = 1_801_396_800
FEB_28 = 1_803_816_000
MAR_31 = 1_806_494_400
FEB_28_2028 = 1_835_352_000


def stripe_sub(anchor, status="active"):
    """A Stripe subscription billed from `anchor`."""
    sub = MagicMock(status=status)
    sub.__getitem__.side_effect = {"billing_cycle_anchor": anchor}.__getitem__
    return sub


@pytest.fixture
def one_off(subscription_item_factory, plan_factory, mocker):
    """A one-time purchase whose term ends Feb 28, billed from Jan 31.

    Returns the subscription and the mocked Stripe subscription service.
    """

    def make(anchor=JAN_31, status="active", interval="monthly", **subscription):
        plan = plan_factory(base_price=100)
        plan.auto_renew = False
        plan.save()
        fields = {
            "subscription_id": "sub_once",
            "kind": "one_off",
            "interval": interval,
            "cancelled": True,
            "cancel_at": date(2027, 2, 28),
            "current_period_end": datetime.fromtimestamp(FEB_28, tz=dt_timezone.utc),
            **subscription,
        }
        item = subscription_item_factory(
            plan=plan,
            **{f"subscription__{key}": value for key, value in fields.items()},
        )
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            stripe_sub(anchor, status),
        )
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=Mock(stripe_payment_method_id="pm_test"),
        )
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.get_current_period_end.return_value = FEB_28
        service.modify.return_value = None
        return item.subscription, service

    return make


class TestExtend:
    @pytest.mark.django_db()
    def test_stripe_ends_it_one_term_later(self, one_off):
        """At the anchor's day, not the period end's: Feb 28 runs to Mar 31."""
        subscription, service = one_off()

        subscription.extend()

        kwargs = service.modify.call_args.kwargs
        assert kwargs["cancel_at"] == MAR_31
        # A term ending off its period's boundary would be prorated.
        assert kwargs["proration_behavior"] == "none"

    @pytest.mark.django_db()
    def test_an_annual_purchase_runs_a_year_more(self, one_off):
        subscription, service = one_off(interval="annual", anchor=FEB_28)

        subscription.extend()

        assert service.modify.call_args.kwargs["cancel_at"] == FEB_28_2028

    @pytest.mark.django_db()
    def test_it_still_ends_on_the_new_date(self, one_off):
        subscription, _service = one_off()

        subscription.extend()

        subscription.refresh_from_db()
        assert subscription.cancelled
        assert subscription.cancel_at == date(2027, 3, 31)
        assert subscription.extended

    @pytest.mark.django_db()
    def test_a_renewing_subscription_is_refused(self, one_off):
        subscription, service = one_off(kind="renewing")

        with pytest.raises(SubscriptionError):
            subscription.extend()
        service.modify.assert_not_called()

    @pytest.mark.django_db()
    def test_a_second_extension_is_refused(self, one_off):
        """Already past this period: one more term at a time."""
        subscription, service = one_off(cancel_at=date(2027, 3, 31))

        with pytest.raises(SubscriptionError):
            subscription.extend()
        service.modify.assert_not_called()

    @pytest.mark.django_db()
    def test_an_unpaid_purchase_is_refused(self, one_off):
        subscription, service = one_off(status="incomplete")

        with pytest.raises(SubscriptionError):
            subscription.extend()
        service.modify.assert_not_called()

    @pytest.mark.django_db()
    def test_a_card_payer_needs_a_card(self, one_off, mocker):
        """The renewal is charged automatically."""
        subscription, service = one_off()
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=Mock(stripe_payment_method_id=""),
        )

        with pytest.raises(ValidationError):
            subscription.extend()
        service.modify.assert_not_called()

    @pytest.mark.django_db()
    def test_an_invoiced_organization_needs_no_card(self, one_off, mocker):
        """Its renewal is a bill it pays."""
        subscription, service = one_off(collection_method="send_invoice")
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=Mock(stripe_payment_method_id=""),
        )

        subscription.extend()

        service.modify.assert_called_once()


class TestExtendSubscription:
    @pytest.mark.django_db()
    def test_it_is_logged_against_each_plan(self, one_off, user_factory):
        subscription, _service = one_off()
        user = user_factory()
        organization = subscription.organization
        plan = subscription.items.get().plan

        organization.extend_subscription(subscription, user=user)

        log = organization.change_logs.get()
        assert log.user == user
        assert log.reason == ChangeLogReason.updated
        assert log.from_plan == plan
        assert log.to_plan == plan
