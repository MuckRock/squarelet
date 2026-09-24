"""Cancellation on a subscription and on its lines.

`cancelled` and `cancel_at` are one fact stored in two fields, on two
models, written from several places - which is where every bug in this area
has come from.  Split out of `test_subscription` to keep both readable.
"""

# A fixture and the parameter that receives it necessarily share a name, and
# a fixture requested only for the patching it does has no body to use it in.
# pylint: disable=redefined-outer-name,unused-argument,too-many-positional-arguments

# Standard Library
from datetime import date, datetime, timezone as dt_timezone

# Third Party
import pytest

# Squarelet
from squarelet.organizations import tasks
from squarelet.organizations.models import SubscriptionItem

# Midday, so a cancellation date cannot be moved by a timezone.
PERIOD_END = datetime(2026, 10, 20, 12, tzinfo=dt_timezone.utc)
ENDS_ON = date(2026, 10, 20)


@pytest.fixture
def no_stripe_subscription(mocker):
    """No Stripe subscription behind the lines under test."""
    return mocker.patch(
        "squarelet.organizations.models.Subscription.stripe_subscription", None
    )


@pytest.fixture
def stripe_subscription(mocker):
    """A Stripe subscription that exists but answers nothing in particular."""
    return mocker.patch(
        "squarelet.organizations.models.Subscription.stripe_subscription"
    )


@pytest.fixture
def subscription_service(mocker):
    """The Stripe-facing service, answering None so cached fields stand."""
    service = mocker.patch(
        "squarelet.organizations.models.payment.get_payment_provider"
    ).return_value.get_subscription_service.return_value
    service.modify.return_value = None
    service.cancel_at_period_end.return_value = None
    service.uncancel.return_value = None
    return service


@pytest.fixture
def quiet_join(mocker):
    """Let a line join without settling a charge against a Mock invoice."""
    mocker.patch(
        "squarelet.organizations.models.Subscription.stripe_modify", return_value=None
    )
    mocker.patch(
        "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
    )


@pytest.fixture
def paid_plan(plan_factory):
    """A plan that renews and costs something."""
    return lambda name, price=30: plan_factory(name=name, base_price=price)


@pytest.fixture
def free_plan(plan_factory):
    """A plan Stripe never sees."""
    return lambda name="Free Plan": plan_factory(
        name=name, base_price=0, price_per_user=0
    )


@pytest.fixture
def one_off_plan(plan_factory):
    """A plan that bills once and stops."""

    def build(name="One Off", price=25):
        plan = plan_factory(name=name, base_price=price)
        plan.auto_renew = False
        plan.save()
        return plan

    return build


@pytest.fixture
def subscription_with(subscription_item_factory):
    """Lines billing on one subscription, one per plan given."""

    def build(*plans, subscription_id="sub_test", period_end=PERIOD_END, **extra):
        first, *rest = plans
        line = subscription_item_factory(
            plan=first,
            subscription__subscription_id=subscription_id,
            subscription__current_period_end=period_end,
            **{f"subscription__{k}": v for k, v in extra.items()},
        )
        return [line] + [
            subscription_item_factory(subscription=line.subscription, plan=plan)
            for plan in rest
        ]

    return build


def join(subscription, plan):
    """Buy `plan` onto the organization that holds `subscription`."""
    item, _ = SubscriptionItem.objects.start(
        organization=subscription.organization, plan=plan
    )
    return item


@pytest.mark.django_db()
class TestAPendingCancellationSurvives:
    """Cancel only what was cancelled.

    Touching any line on a subscription with a pending cancellation must not
    revive it, locally or on Stripe.
    """

    @pytest.fixture
    def modify(
        self, subscription_with, paid_plan, stripe_subscription, subscription_service
    ):
        def run(cancelled):
            (line,) = subscription_with(paid_plan("Only Plan"), subscription_id="sub_1")
            if cancelled:
                line.subscription.cancelled = True
                line.subscription.save()
            line.subscription.stripe_modify()
            return line.subscription, subscription_service.modify.call_args.kwargs

        return run

    def test_the_local_flag_is_left_alone(self, modify):
        subscription, _kwargs = modify(cancelled=True)

        subscription.refresh_from_db()
        assert subscription.cancelled

    def test_stripe_is_still_told_to_cancel(self, modify):
        _subscription, kwargs = modify(cancelled=True)

        assert kwargs["cancel_at_period_end"] is True

    def test_an_uncancelled_subscription_is_unaffected(self, modify):
        subscription, kwargs = modify(cancelled=False)

        subscription.refresh_from_db()
        assert not subscription.cancelled
        assert kwargs["cancel_at_period_end"] is False


@pytest.mark.django_db()
class TestTheCancellationPairMovesTogether:
    """`cancelled` and `cancel_at` are one fact, not two fields.

    The nightly sweep deletes anything `cancelled` whose `cancel_at` has
    arrived *or is null*, so a flag left set without a date means "delete
    this tonight" - subscription, lines and all.
    """

    @pytest.fixture
    def paid_line(self, subscription_with, professional_plan_factory):
        (line,) = subscription_with(
            professional_plan_factory(), subscription_id="sub_live"
        )
        return line

    def test_downgrading_to_free_clears_a_pending_cancellation(
        self, paid_line, free_plan, stripe_subscription, subscription_service
    ):
        """The one that deleted a live subscription.

        Cancelling and then downgrading to free deletes the Stripe
        subscription, which is the end of the cancellation - the flag must
        not survive with its date cleared.
        """
        paid_line.subscription.cancel()

        paid_line.modify(free_plan("Free Tier"))

        subscription = paid_line.subscription
        subscription.refresh_from_db()
        paid_line.refresh_from_db()
        assert not subscription.cancelled
        assert subscription.cancel_at is None
        assert not paid_line.cancelled
        assert paid_line.cancel_at is None

    def test_changing_plan_clears_the_line_s_pending_cancellation(
        self,
        paid_line,
        subscription_item_factory,
        paid_plan,
        professional_plan_factory,
        no_stripe_subscription,
        mocker,
    ):
        """The cancellation belonged to the plan that just got replaced.

        Left in place it stops the line the customer has moved onto, on the
        old plan's date, while they are paying for it.
        """
        # Paid: cancelling the last line Stripe bills would take the whole
        # subscription with it.
        subscription_item_factory(
            subscription=paid_line.subscription, plan=paid_plan("Second Plan")
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        paid_line.cancel()
        assert paid_line.cancelled

        paid_line.modify(professional_plan_factory(name="Other Paid", base_price=30))

        paid_line.refresh_from_db()
        assert not paid_line.cancelled
        assert paid_line.cancel_at is None

    def test_changing_to_a_one_off_plan_schedules_the_line_to_stop(
        self, paid_line, one_off_plan, no_stripe_subscription, mocker
    ):
        """The cancellation is re-derived, not just dropped."""
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")

        paid_line.modify(one_off_plan(price=30))

        paid_line.refresh_from_db()
        assert paid_line.cancelled
        assert paid_line.cancel_at == ENDS_ON

    def test_changing_the_last_renewing_line_to_a_one_off_ends_the_subscription(
        self,
        paid_line,
        subscription_item_factory,
        paid_plan,
        one_off_plan,
        no_stripe_subscription,
        mocker,
    ):
        """Nothing would renew, so Stripe has to be told to stop."""
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        other = subscription_item_factory(
            subscription=paid_line.subscription, plan=paid_plan("Second Plan")
        )
        other.cancel()

        paid_line.modify(one_off_plan(price=30))

        paid_line.subscription.refresh_from_db()
        assert paid_line.subscription.cancelled

    def test_a_plan_change_that_starts_billing_ends_on_the_new_period(
        self, subscription_with, free_plan, one_off_plan, no_stripe_subscription, mocker
    ):
        """No period exists until Stripe starts the subscription."""

        def start(subscription, *args, **kwargs):
            subscription.current_period_end = PERIOD_END
            subscription.save()

        mocker.patch(
            "squarelet.organizations.models.Subscription.sync_to_stripe",
            autospec=True,
            side_effect=start,
        )
        line, _free = subscription_with(
            free_plan("Free One"),
            free_plan("Free Two"),
            subscription_id="",
            period_end=None,
        )

        line.modify(one_off_plan(price=30))

        line.refresh_from_db()
        assert line.cancelled
        assert line.cancel_at == ENDS_ON

    def test_a_free_line_does_not_keep_stripe_renewing(
        self, subscription_with, one_off_plan, free_plan
    ):
        """Stripe never sees the free line, so only the one-off counts."""
        line, _free = subscription_with(one_off_plan(), free_plan())

        assert not line.subscription.auto_renew

    def test_a_cancelled_subscription_is_not_revived_by_a_plan_change(
        self, paid_line, professional_plan_factory, no_stripe_subscription, mocker
    ):
        """Only `uncancel` reverses a whole-subscription cancellation."""
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        paid_line.subscription.cancelled = True
        paid_line.subscription.save()
        paid_line.cancelled = True
        paid_line.save()

        paid_line.modify(professional_plan_factory(name="Other Paid", base_price=30))

        paid_line.refresh_from_db()
        assert paid_line.cancelled


@pytest.mark.django_db()
class TestRevivingOnlyWhatTheSubscriptionEnded:
    """Resubscribe must not hand back plans nobody asked for.

    Stripe has no per-item cancellation, so a line the customer stopped by
    itself is invisible to it - only `cancelled_by_subscription` tells the
    two apart.
    """

    @pytest.fixture
    def three_lines(self, subscription_with, paid_plan):
        return subscription_with(
            paid_plan("Line One"),
            paid_plan("Line Two"),
            paid_plan("Line Three"),
            subscription_id="sub_three",
        )

    def test_a_line_the_customer_cancelled_stays_cancelled(
        self, three_lines, stripe_subscription, subscription_service, mocker
    ):
        """Cancel two lines, then end the whole subscription.

        The third was still renewing when the subscription went, so it comes
        back with it; the first two are the customer's own decision.
        """
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=mocker.Mock(stripe_payment_method_id="pm_test"),
        )
        one, two, three = three_lines
        one.cancel()
        two.cancel()
        # Not `three.cancel()`: that is the customer ending the last plan,
        # and the subscription follows *because of* it.  This is the other
        # shape, where something ends the subscription over the top of a
        # line that was still renewing.
        three.subscription.cancel()

        three.subscription.refresh_from_db()
        three.subscription.uncancel()

        for line in (one, two, three):
            line.refresh_from_db()
        assert one.cancelled, "the customer cancelled this one themselves"
        assert two.cancelled, "and this one"
        assert not three.cancelled, "only the subscription's own ending is reversed"

    def test_reversing_from_stripe_revives_the_line_that_ended_it(
        self, subscription_with, paid_plan, one_off_plan
    ):
        """Otherwise Stripe renews a subscription whose only line is ending."""
        line, pack = subscription_with(
            paid_plan("Only Plan"), one_off_plan(), subscription_id="sub_only"
        )
        for item in (line, pack):
            item.mark_cancelled(item.subscription.current_period_end)
            item.save()
        subscription = line.subscription
        subscription.mark_cancelled(subscription.current_period_end)
        subscription.save()

        tasks.handle_subscription_updated(
            {"id": "sub_only", "status": "active", "cancel_at_period_end": False}
        )

        line.refresh_from_db()
        pack.refresh_from_db()
        assert not line.cancelled
        assert pack.cancelled, "a one-off still bills only once"

    def test_downgrading_a_cancelled_plan_to_free_keeps_it(
        self,
        subscription_with,
        paid_plan,
        free_plan,
        stripe_subscription,
        subscription_service,
    ):
        """The free plan is what they chose to keep."""
        (line,) = subscription_with(paid_plan("Only Plan"), subscription_id="sub_only")
        line.cancel()

        line.modify(free_plan())

        line.refresh_from_db()
        assert not line.cancelled

    def test_reversing_from_stripe_does_not_revive_them_either(self, three_lines):
        """Same rule, reached from Stripe rather than from Resubscribe."""
        one, two, _three = three_lines
        # Cancelled by the customer, before the subscription was.
        one.mark_cancelled(one.subscription.current_period_end)
        one.save()
        subscription = one.subscription
        subscription.mark_cancelled(subscription.current_period_end)
        subscription.save()
        subscription.push_cancellation_to_items()

        tasks.handle_subscription_updated(
            {"id": "sub_three", "status": "active", "cancel_at_period_end": False}
        )

        one.refresh_from_db()
        two.refresh_from_db()
        assert one.cancelled, "cancelled by the customer, not by Stripe"
        assert one.cancel_at is not None
        assert not two.cancelled, "this one only ended because the subscription did"


@pytest.mark.django_db()
class TestResubscribeIsPerLine:
    """Resubscribe brings back the plan you pressed it on.

    Cancelling the last active line escalates to the whole subscription, and
    that must not file the line the customer just cancelled under "the
    subscription did this" - or Resubscribe returns a different plan from the
    one they pressed it on.
    """

    @pytest.fixture
    def three_plans(self, subscription_with, paid_plan, no_stripe_subscription, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_payment_method_id",
            new_callable=mocker.PropertyMock,
            return_value="pm_x",
        )
        lines = subscription_with(
            paid_plan("A", price=10),
            paid_plan("B", price=20),
            paid_plan("C", price=30),
            subscription_id="sub_three",
        )
        for line in lines:
            line.cancel()
        for line in lines:
            line.refresh_from_db()
        subscription = lines[0].subscription
        subscription.refresh_from_db()
        return subscription, lines

    def test_cancelling_the_last_line_is_still_that_line_own_decision(
        self, three_plans
    ):
        """The subscription ends *because of* it, not the other way round."""
        subscription, (_a, _b, c) = three_plans

        assert subscription.cancelled
        assert c.cancelled and not c.cancelled_by_subscription

    def test_resubscribing_revives_the_line_it_was_called_on(self, three_plans):
        _subscription, (a, _b, _c) = three_plans

        a.uncancel()

        a.refresh_from_db()
        assert not a.cancelled

    def test_it_leaves_the_other_cancelled_plans_alone(self, three_plans):
        subscription, (a, b, c) = three_plans

        a.uncancel()

        for line in (b, c):
            line.refresh_from_db()
        assert b.cancelled, "never asked for back"
        assert c.cancelled, "never asked for back"
        subscription.refresh_from_db()
        assert not subscription.cancelled, "there is an active plan again"
