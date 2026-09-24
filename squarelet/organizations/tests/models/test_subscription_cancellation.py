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
