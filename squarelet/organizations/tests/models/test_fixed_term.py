"""A fixed term billed monthly ends on its own date, not its period's."""

# Standard Library
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import MagicMock, Mock

# Third Party
import pytest


class TestAChangeKeepsTheTerm:
    """What `stripe_modify` sends Stripe for a subscription with an end date."""

    @staticmethod
    def _stripe_sub_ending(cancel_at):
        """A Stripe subscription that Stripe itself will end at `cancel_at`."""
        stripe_sub = MagicMock()
        stripe_sub.__contains__.side_effect = lambda key: key == "cancel_at"
        stripe_sub.__getitem__.side_effect = {"cancel_at": cancel_at}.__getitem__
        return stripe_sub

    def _modify_a_fixed_term(self, mocker, subscription_item_factory, plan_factory):
        """Change a fixed term billed monthly whose end is past this period.

        Returns the modify call and the subscription.
        """
        plan = plan_factory(base_price=100)
        plan.auto_renew = False
        plan.save()
        item = subscription_item_factory(
            plan=plan,
            subscription__subscription_id="sub_term",
            subscription__cancelled=True,
            subscription__cancel_at=date(2027, 8, 9),
        )
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_svc.modify.return_value = Mock(status="active")
        mock_sub_svc.get_current_period_end.return_value = self.PERIOD_END
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            self._stripe_sub_ending(self.TERM_END),
        )

        item.subscription.stripe_modify()

        return mock_sub_svc.modify.call_args.kwargs, item.subscription

    # Midday Nov 9 2026 and Aug 9 2027.
    PERIOD_END = 1_794_247_200
    TERM_END = 1_817_834_400

    @pytest.mark.django_db()
    def test_a_change_keeps_an_end_date_past_the_period(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """Either `cancel_at_period_end` would wipe Stripe's own end date."""
        kwargs, _subscription = self._modify_a_fixed_term(
            mocker, subscription_item_factory, plan_factory
        )

        assert kwargs["cancel_at"] == self.TERM_END
        assert "cancel_at_period_end" not in kwargs

    @pytest.mark.django_db()
    def test_a_change_leaves_the_end_date_where_stripe_has_it(
        self, subscription_item_factory, plan_factory, mocker
    ):
        _kwargs, subscription = self._modify_a_fixed_term(
            mocker, subscription_item_factory, plan_factory
        )

        subscription.refresh_from_db()
        assert subscription.cancelled
        assert subscription.cancel_at == date(2027, 8, 9)

    @pytest.mark.django_db()
    def test_an_end_at_the_period_end_still_ends_at_the_period_end(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """What a cancellation from the app sets, which renewals must not keep."""
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_end",
            subscription__cancelled=True,
        )
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_svc.modify.return_value = Mock(status="active")
        mock_sub_svc.get_current_period_end.return_value = self.PERIOD_END
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            self._stripe_sub_ending(self.PERIOD_END),
        )

        item.subscription.stripe_modify()

        kwargs = mock_sub_svc.modify.call_args.kwargs
        assert kwargs["cancel_at_period_end"] is True
        assert "cancel_at" not in kwargs


class TestSubscriptionEndDate:
    """The day a cancelled subscription stops, as the billing pages show it."""

    @pytest.mark.django_db()
    def test_a_fixed_term_ends_on_its_own_date(self, subscription_factory):
        """Not when the current month's billing period does."""
        subscription = subscription_factory(
            cancelled=True,
            cancel_at=date(2027, 8, 9),
            current_period_end=datetime(2026, 11, 9, 18, tzinfo=dt_timezone.utc),
        )
        assert subscription.end_date == date(2027, 8, 9)

    @pytest.mark.django_db()
    def test_without_a_date_it_ends_with_the_period(self, subscription_factory):
        subscription = subscription_factory(
            cancelled=True,
            current_period_end=datetime(2026, 11, 9, 18, tzinfo=dt_timezone.utc),
        )
        assert subscription.end_date == date(2026, 11, 9)

    @pytest.mark.django_db()
    def test_a_renewing_subscription_has_no_end(self, subscription_factory):
        subscription = subscription_factory(
            current_period_end=datetime(2026, 11, 9, 18, tzinfo=dt_timezone.utc),
        )
        assert subscription.end_date is None
