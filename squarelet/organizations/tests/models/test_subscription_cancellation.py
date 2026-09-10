"""Cancellation on a subscription and on its lines.

`cancelled` and `cancel_at` are one fact stored in two fields, on two
models, written from several places - which is where every bug in this area
has come from.  Split out of `test_subscription` to keep both readable.
"""

# Standard Library
from datetime import date, datetime, timezone as dt_timezone

# Third Party
import pytest

# Squarelet
from squarelet.organizations import tasks
from squarelet.organizations.models import SubscriptionItem
from squarelet.organizations.payments.exceptions import SubscriptionError


@pytest.mark.django_db()
class TestAPendingCancellationSurvives:
    """Cancel only what was cancelled.

    `stripe_modify` used to clear `cancelled` on every call and send
    `cancel_at_period_end=not auto_renew`, so touching any line on a
    subscription with a pending cancellation revived it - locally and on
    Stripe - without anyone asking.
    """

    def _modify(self, subscription, mocker):
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.modify.return_value = None
        subscription.stripe_modify()
        return service.modify.call_args.kwargs

    def test_the_local_flag_is_left_alone(self, subscription_item_factory, mocker):
        item = subscription_item_factory(subscription__subscription_id="sub_1")
        subscription = item.subscription
        subscription.cancelled = True
        subscription.save()

        self._modify(subscription, mocker)

        subscription.refresh_from_db()
        assert subscription.cancelled

    def test_stripe_is_still_told_to_cancel(self, subscription_item_factory, mocker):
        item = subscription_item_factory(subscription__subscription_id="sub_1")
        subscription = item.subscription
        subscription.cancelled = True
        subscription.save()

        kwargs = self._modify(subscription, mocker)

        assert kwargs["cancel_at_period_end"] is True

    def test_an_uncancelled_subscription_is_unaffected(
        self, subscription_item_factory, mocker
    ):
        item = subscription_item_factory(subscription__subscription_id="sub_1")

        kwargs = self._modify(item.subscription, mocker)

        item.subscription.refresh_from_db()
        assert not item.subscription.cancelled
        assert kwargs["cancel_at_period_end"] is False


@pytest.mark.django_db()
class TestTheCancellationPairMovesTogether:
    """`cancelled` and `cancel_at` are one fact, not two fields.

    The nightly sweep deletes anything `cancelled` whose `cancel_at` has
    arrived *or is null*, so a flag left set without a date means "delete
    this tonight" - subscription, lines and all.  Every path that changes
    what an organization is subscribed to has to leave the pair agreeing
    with reality.
    """

    def _paid_line(self, subscription_item_factory, professional_plan_factory):
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_live",
        )
        item.subscription.current_period_end = datetime(
            2026, 9, 20, 12, tzinfo=dt_timezone.utc
        )
        item.subscription.save()
        return item

    def test_downgrading_to_free_clears_a_pending_cancellation(
        self,
        subscription_item_factory,
        plan_factory,
        professional_plan_factory,
        mocker,
    ):
        """The one that deleted a live subscription.

        Cancelling and then downgrading to free deletes the Stripe
        subscription, which is the end of the cancellation - but the flag
        used to survive with its date cleared, and the sweep read that as
        due immediately.
        """
        item = self._paid_line(subscription_item_factory, professional_plan_factory)
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        # Nothing came back from Stripe, so the cached period end stands.
        service.cancel_at_period_end.return_value = None
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        item.subscription.cancel()

        item.modify(plan_factory(name="Free Tier", base_price=0, price_per_user=0))

        subscription = item.subscription
        subscription.refresh_from_db()
        item.refresh_from_db()
        assert not subscription.cancelled
        assert subscription.cancel_at is None
        assert not item.cancelled
        assert item.cancel_at is None

    def test_changing_plan_clears_the_line_s_pending_cancellation(
        self, subscription_item_factory, professional_plan_factory, plan_factory, mocker
    ):
        """The cancellation belonged to the plan that just got replaced.

        Left in place it stops the line the customer has moved onto, on the
        old plan's date, while they are paying for it.
        """
        item = self._paid_line(subscription_item_factory, professional_plan_factory)
        # Paid: a free sibling is nothing Stripe bills, so cancelling the
        # line below would be cancelling the subscription's last real line
        # and would take the whole subscription with it.
        subscription_item_factory(
            subscription=item.subscription,
            plan=plan_factory(name="Second Plan", base_price=30),
        )
        # `modify` identifies the line on Stripe before changing its
        # plan; nothing here is exercising that.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            None,
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        item.cancel()
        assert item.cancelled

        item.modify(professional_plan_factory(name="Other Paid", base_price=30))

        item.refresh_from_db()
        assert not item.cancelled
        assert item.cancel_at is None

    def test_changing_to_a_one_off_plan_schedules_the_line_to_stop(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """The cancellation is re-derived, not just dropped."""
        item = self._paid_line(subscription_item_factory, professional_plan_factory)
        one_off = professional_plan_factory(name="One Off", base_price=30)
        one_off.auto_renew = False
        one_off.save()
        # `modify` identifies the line on Stripe before changing its
        # plan; nothing here is exercising that.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            None,
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")

        item.modify(one_off)

        item.refresh_from_db()
        assert item.cancelled
        assert item.cancel_at == date(2026, 9, 20)

    def test_a_cancelled_subscription_is_not_revived_by_a_plan_change(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """Only `uncancel` reverses a whole-subscription cancellation."""
        item = self._paid_line(subscription_item_factory, professional_plan_factory)
        # `modify` identifies the line on Stripe before changing its
        # plan; nothing here is exercising that.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            None,
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        item.subscription.cancelled = True
        item.subscription.save()
        item.cancelled = True
        item.save()

        item.modify(professional_plan_factory(name="Other Paid", base_price=30))

        item.refresh_from_db()
        assert item.cancelled


@pytest.mark.django_db()
class TestRevivingOnlyWhatTheSubscriptionEnded:
    """Resubscribe must not hand back plans nobody asked for.

    Stripe has no per-item cancellation, so a line the customer stopped by
    itself is invisible to it.  Nothing arriving from Stripe - and no
    reversal of the subscription's own cancellation - is an answer about
    those lines, and only `cancelled_with_subscription` can tell them apart.
    """

    def _three_paid_lines(self, subscription_item_factory, plan_factory):
        first = subscription_item_factory(
            plan=plan_factory(name="Line One", base_price=30),
            subscription__subscription_id="sub_three",
            # Midday, so a cancellation date is real and cannot be moved by
            # a timezone.
            subscription__current_period_end=datetime(
                2026, 10, 20, 12, tzinfo=dt_timezone.utc
            ),
        )
        rest = [
            subscription_item_factory(
                subscription=first.subscription,
                plan=plan_factory(name=name, base_price=30),
            )
            for name in ("Line Two", "Line Three")
        ]
        return [first, *rest]

    def test_a_line_the_customer_cancelled_stays_cancelled(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """Cancel two, then resubscribe: only the third comes back."""
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=mocker.Mock(stripe_payment_method_id="pm_test"),
        )
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        # Nothing comes back from Stripe, so the cached fields stand rather
        # than being overwritten with Mocks.
        service.cancel_at_period_end.return_value = None
        service.uncancel.return_value = None
        one, two, three = self._three_paid_lines(
            subscription_item_factory, plan_factory
        )
        one.cancel()
        two.cancel()
        # The third is the last paid line still renewing, so cancelling it
        # ends the whole subscription.
        three.cancel()

        three.subscription.refresh_from_db()
        three.subscription.uncancel()

        for line in (one, two, three):
            line.refresh_from_db()
        assert one.cancelled, "the customer cancelled this one themselves"
        assert two.cancelled, "and this one"
        assert not three.cancelled, "only the subscription's own ending is reversed"

    def test_reversing_from_stripe_does_not_revive_them_either(
        self, subscription_item_factory, plan_factory
    ):
        """Same rule, reached from Stripe rather than from Resubscribe.

        A cancellation lifted in the Stripe dashboard reverses the
        subscription's ending, and the lines it ended go with it - but a
        line the customer stopped by itself was never Stripe's to reverse.
        """
        one, two, _three = self._three_paid_lines(
            subscription_item_factory, plan_factory
        )
        # Cancelled by the customer, before the subscription was.
        one.mark_cancelled(one.subscription.current_period_end)
        one.save()
        subscription = one.subscription
        subscription.mark_cancelled(subscription.current_period_end)
        subscription.save()
        subscription.push_cancellation_to_items()

        tasks.handle_subscription_updated(
            {
                "id": "sub_three",
                "status": "active",
                "cancel_at_period_end": False,
            }
        )

        one.refresh_from_db()
        two.refresh_from_db()
        assert one.cancelled, "cancelled by the customer, not by Stripe"
        assert one.cancel_at is not None
        assert not two.cancelled, "this one only ended because the subscription did"


@pytest.mark.django_db()
class TestAOneTimePurchaseCannotBeResumed:
    """It is flagged to end the moment it is bought.

    That is what "bills once" means, but it reads as cancelled on the
    billing page - and a Resubscribe button beside it would turn a one-time
    purchase into a recurring charge, because a subscription renews if any
    line does.
    """

    def _one_off_beside_a_renewing_plan(
        self, subscription_item_factory, plan_factory, mocker
    ):
        # None, so the line-joining path does not go on to settle a charge
        # against a Mock invoice.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_modify",
            return_value=None,
        )
        mocker.patch(
            "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
        )
        renewing = subscription_item_factory(
            plan=plan_factory(name="Renewing Plan", base_price=30),
            subscription__subscription_id="sub_oneoff",
            subscription__current_period_end=datetime(
                2026, 10, 20, 12, tzinfo=dt_timezone.utc
            ),
        )
        one_off = plan_factory(name="Credit Pack", base_price=25)
        one_off.auto_renew = False
        one_off.save()
        pack, _ = SubscriptionItem.objects.start(
            organization=renewing.subscription.organization, plan=one_off
        )
        return pack

    def test_it_arrives_already_flagged_to_end(
        self, subscription_item_factory, plan_factory, mocker
    ):
        pack = self._one_off_beside_a_renewing_plan(
            subscription_item_factory, plan_factory, mocker
        )

        pack.refresh_from_db()
        assert pack.cancelled, "a plan that bills once stops after that period"

    def test_resuming_it_is_refused(
        self, subscription_item_factory, plan_factory, mocker
    ):
        pack = self._one_off_beside_a_renewing_plan(
            subscription_item_factory, plan_factory, mocker
        )

        with pytest.raises(SubscriptionError, match="one-time purchase"):
            pack.uncancel()

        pack.refresh_from_db()
        assert pack.cancelled, "still ending, not quietly made recurring"


@pytest.mark.django_db()
class TestUpgradingAwayFromAOneOffPlan:
    """A subscription ending because nothing renews is ending because of plans.

    Changing the plan changes the reason.  Left in place, the ending is
    re-sent to Stripe as cancel_at_period_end and the plan the customer has
    just bought is deleted at the end of the period they bought it for.
    """

    def _single_one_off_line(self, subscription_item_factory, plan_factory, mocker):
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.modify.return_value = None
        one_off = plan_factory(name="One Off", base_price=25)
        one_off.auto_renew = False
        one_off.save()
        item = subscription_item_factory(
            plan=one_off,
            subscription__subscription_id="sub_oneoff",
            subscription__cancelled=True,
            subscription__current_period_end=datetime(
                2026, 10, 20, 12, tzinfo=dt_timezone.utc
            ),
        )
        item.mark_cancelled(item.subscription.current_period_end)
        item.save()
        return item

    def test_upgrading_to_a_renewing_plan_lifts_the_ending(
        self, subscription_item_factory, plan_factory, mocker
    ):
        item = self._single_one_off_line(
            subscription_item_factory, plan_factory, mocker
        )

        item.modify(plan_factory(name="Renewing Plan", base_price=30))

        item.refresh_from_db()
        item.subscription.refresh_from_db()
        assert not item.subscription.cancelled, "nothing is ending any more"
        assert not item.cancelled, "the plan they just bought is not going away"

    def test_a_cancellation_the_customer_asked_for_survives(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """Only a *derived* ending is lifted; a decision is not."""
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.modify.return_value = None
        item = subscription_item_factory(
            plan=plan_factory(name="Renewing One", base_price=30),
            subscription__subscription_id="sub_asked",
            subscription__cancelled=True,
            subscription__current_period_end=datetime(
                2026, 10, 20, 12, tzinfo=dt_timezone.utc
            ),
        )

        item.modify(plan_factory(name="Renewing Two", base_price=40))

        item.subscription.refresh_from_db()
        assert item.subscription.cancelled, "the customer cancelled this"


@pytest.mark.django_db()
class TestBuyingOntoACancellingSubscription:
    """A plan bought while cancelling is a plan the customer means to keep.

    Stripe's `cancel_at_period_end` belongs to the subscription, so the new
    line would be deleted along with everything else when the period ran
    out - paid for and silently lost.  Lifting the cancellation is the only
    way to keep it, and the line they actually cancelled has to survive
    that, on its own date.
    """

    def _cancelling(self, subscription_item_factory, plan_factory, mocker):
        # None, so the line-joining path does not go on to settle a charge
        # against a Mock invoice.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_modify",
            return_value=None,
        )
        mocker.patch(
            "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
        )
        leaving = subscription_item_factory(
            plan=plan_factory(name="Leaving Plan", base_price=30),
            subscription__subscription_id="sub_leaving",
            subscription__current_period_end=datetime(
                2026, 10, 20, 12, tzinfo=dt_timezone.utc
            ),
        )
        subscription = leaving.subscription
        subscription.mark_cancelled(subscription.current_period_end)
        subscription.save()
        subscription.push_cancellation_to_items()
        leaving.refresh_from_db()
        return leaving

    def _join(self, leaving, plan):
        item, _ = SubscriptionItem.objects.start(
            organization=leaving.subscription.organization, plan=plan
        )
        return item

    def test_the_subscription_carries_on(
        self, subscription_item_factory, plan_factory, mocker
    ):
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)

        self._join(leaving, plan_factory(name="Arriving Plan", base_price=40))

        leaving.subscription.refresh_from_db()
        assert not leaving.subscription.cancelled
        assert leaving.subscription.cancel_at is None

    def test_the_new_line_is_not_ending(
        self, subscription_item_factory, plan_factory, mocker
    ):
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)

        arriving = self._join(
            leaving, plan_factory(name="Arriving Plan", base_price=40)
        )

        arriving.refresh_from_db()
        assert not arriving.cancelled

    def test_the_cancelled_line_still_ends_on_its_own_date(
        self, subscription_item_factory, plan_factory, mocker
    ):
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)
        ends_on = leaving.cancel_at

        self._join(leaving, plan_factory(name="Arriving Plan", base_price=40))

        leaving.refresh_from_db()
        assert leaving.cancelled
        assert leaving.cancel_at == ends_on

    def test_resubscribing_does_not_revive_it(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """It is ending in its own right now, not because its parent was.

        Which is the whole point of the conversion: `uncancel` and the
        Stripe webhook revive only `cancelled_with_subscription` lines.
        """
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)

        self._join(leaving, plan_factory(name="Arriving Plan", base_price=40))

        leaving.refresh_from_db()
        assert not leaving.cancelled_with_subscription
        # What `uncancel` does once Stripe has been told to renew.
        leaving.subscription.refresh_from_db()
        leaving.subscription.push_cancellation_to_items()
        leaving.refresh_from_db()
        assert leaving.cancelled, "the customer asked for this one to end"

    def test_a_free_line_leaves_the_cancellation_alone(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """A free line is never billed, so it cannot be a reason to renew.

        Carrying on for one would leave Stripe renewing a subscription
        whose only paid line is cancelled - which nothing can sweep.
        """
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)

        self._join(
            leaving,
            plan_factory(name="Free Plan", base_price=0, price_per_user=0),
        )

        leaving.subscription.refresh_from_db()
        assert leaving.subscription.cancelled

    def test_a_one_off_leaves_the_cancellation_alone(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """A plan that bills once is flagged to stop the moment it is
        bought, so it is not asking for anything to be renewed either."""
        leaving = self._cancelling(subscription_item_factory, plan_factory, mocker)
        one_off = plan_factory(name="Credit Pack", base_price=25)
        one_off.auto_renew = False
        one_off.save()

        self._join(leaving, one_off)

        leaving.subscription.refresh_from_db()
        assert leaving.subscription.cancelled
