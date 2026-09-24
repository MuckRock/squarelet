"""Stopping one plan: now with a credit beside others, else at period end."""

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import Subscription, SubscriptionItem


@pytest.mark.django_db()
class TestStoppingAPlan:
    """A plan beside other paid plans comes off now; the last one waits."""

    @pytest.fixture
    def stripe_service(self, mocker):
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        return mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value

    def test_a_plan_beside_another_comes_off_now_with_a_credit(
        self, subscription_item_factory, plan_factory, stripe_service
    ):
        leaving = subscription_item_factory(
            plan=plan_factory(name="Leaving", base_price=30),
            subscription__subscription_id="sub_two",
            stripe_item_id="si_leaving",
        )
        subscription_item_factory(
            subscription=leaving.subscription,
            plan=plan_factory(name="Staying", base_price=30),
        )

        assert leaving.cancel() is True

        assert not SubscriptionItem.objects.filter(pk=leaving.pk).exists()
        leaving.subscription.refresh_from_db()
        assert not leaving.subscription.cancelled
        stripe_service.modify.assert_called_once_with(
            "sub_two",
            items=[{"id": "si_leaving", "deleted": True}],
            proration_behavior="create_prorations",
        )

    def test_the_last_paid_plan_waits_for_period_end(
        self, subscription_item_factory, plan_factory, stripe_service
    ):
        """With nothing else billing there is no invoice to credit."""
        stripe_service.cancel_at_period_end.return_value = None
        only = subscription_item_factory(
            plan=plan_factory(name="Only", base_price=30),
            subscription__subscription_id="sub_one",
        )

        assert only.cancel() is False

        assert SubscriptionItem.objects.filter(pk=only.pk).exists()
        only.subscription.refresh_from_db()
        assert only.subscription.cancelled
        stripe_service.modify.assert_not_called()

    def test_a_free_plan_comes_off_now_and_takes_an_empty_row_with_it(
        self, subscription_item_factory, plan_factory
    ):
        free = subscription_item_factory(
            plan=plan_factory(name="Free", base_price=0, price_per_user=0),
            subscription__kind="free",
        )
        subscription = free.subscription

        assert free.cancel() is True

        assert not Subscription.objects.filter(pk=subscription.pk).exists()

    def test_a_plan_on_a_cancelling_subscription_is_left_alone(
        self, subscription_item_factory, plan_factory, stripe_service
    ):
        """It already ends with the subscription; removing it would credit it."""
        line = subscription_item_factory(
            plan=plan_factory(name="Ending", base_price=30),
            subscription__cancelled=True,
        )
        subscription_item_factory(
            subscription=line.subscription,
            plan=plan_factory(name="Also Ending", base_price=30),
        )

        assert line.cancel() is False

        assert SubscriptionItem.objects.filter(pk=line.pk).exists()
        stripe_service.modify.assert_not_called()
        stripe_service.cancel_at_period_end.assert_not_called()


@pytest.mark.django_db()
class TestTheRemovalCredit:
    """The confirm page shows what Stripe will credit, priced at one moment."""

    @pytest.fixture
    def two_lines(self, subscription_item_factory, plan_factory):
        leaving = subscription_item_factory(
            plan=plan_factory(name="Leaving", base_price=30),
            subscription__subscription_id="sub_two",
            stripe_item_id="si_leaving",
        )
        subscription_item_factory(
            subscription=leaving.subscription,
            plan=plan_factory(name="Staying", base_price=30),
        )
        return leaving

    @pytest.fixture
    def stripe_service(self, mocker):
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        mocker.patch("squarelet.organizations.models.Subscription.sync_stripe_item_ids")
        return mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value

    def test_the_credit_is_the_removed_items_proration_only(
        self, two_lines, stripe_service
    ):
        """A credit already waiting from an earlier removal is not this one's."""

        def line(amount, item, proration=True):
            details = {"proration": proration, "subscription_item": item}
            return {"amount": amount, "parent": {"subscription_item_details": details}}

        stripe_service.preview_removal.return_value = {
            "lines": {
                "data": [
                    line(-1240, "si_leaving"),
                    line(-1000, "si_removed_earlier"),
                    line(3000, "si_staying", proration=False),
                ]
            }
        }

        assert two_lines.removal_credit(1_700_000_000) == 1240
        assert stripe_service.preview_removal.call_args.args[1:] == (
            "sub_two",
            "si_leaving",
            1_700_000_000,
        )

    def test_no_amount_when_stripe_does_not_answer(self, two_lines, stripe_service):
        stripe_service.preview_removal.side_effect = stripe.APIConnectionError("down")

        assert two_lines.removal_credit(1_700_000_000) is None

    def test_pricing_the_credit_asks_stripe_only_for_the_preview(
        self, two_lines, stripe_service, mocker
    ):
        """No subscription fetch to fail in an outage, and no writes on a GET."""
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            new_callable=mocker.PropertyMock,
            side_effect=stripe.APIConnectionError("down"),
        )
        sync = mocker.patch(
            "squarelet.organizations.models.Subscription.sync_stripe_item_ids"
        )
        stripe_service.preview_removal.return_value = {"lines": {"data": []}}

        assert two_lines.removal_credit(1_700_000_000) == 0
        sync.assert_not_called()

    def test_the_removal_uses_the_moment_the_credit_was_priced_at(
        self, two_lines, stripe_service
    ):
        two_lines.cancel(proration_date=1_700_000_000)

        assert stripe_service.modify.call_args.kwargs["proration_date"] == 1_700_000_000

    def test_a_moment_from_before_a_renewal_is_dropped(self, two_lines, stripe_service):
        """Stripe refuses a proration date outside the current period."""
        stripe_service.modify.side_effect = [
            stripe.InvalidRequestError("outside the period", "proration_date"),
            None,
        ]

        two_lines.cancel(proration_date=1_700_000_000)

        assert "proration_date" not in stripe_service.modify.call_args.kwargs
        assert not SubscriptionItem.objects.filter(pk=two_lines.pk).exists()
