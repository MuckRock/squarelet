"""The deploy-time command that identifies pre-split subscription lines.

Its counts are what an operator reads to decide the release went well, so
they have to distinguish "nothing to do" from "this Stripe account has never
heard of these subscriptions".
"""

# Django
from django.core.management import call_command

# Standard Library
from io import StringIO

# Third Party
import pytest


@pytest.mark.django_db()
class TestUnknownSubscriptions:
    def test_a_subscription_stripe_does_not_have_is_an_error(
        self, subscription_item_factory, mocker
    ):
        """`retrieve` answers None for one it cannot find, not an exception.

        Counted as "skipped", a whole run against the wrong Stripe account
        looked identical to a run with nothing to do - which is how seven
        unidentified subscriptions reported themselves as fine.
        """
        subscription_item_factory(
            subscription__subscription_id="sub_not_here", stripe_item_id=""
        )
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )
        out, err = StringIO(), StringIO()

        call_command("backfill_stripe_item_ids", stdout=out, stderr=err)

        assert "not found on Stripe" in err.getvalue()
        assert "errors: 1" in out.getvalue()
        assert "skipped: 0" in out.getvalue()
        assert "does not have" in out.getvalue()


@pytest.mark.django_db()
class TestTheRenewalDateIsCachedToo:
    """The split reads `current_period_end` from the database, and the
    migration had nothing to fill it from - so until something wrote it,
    every pre-split subscriber saw "Renews on None".  The subscription is
    fetched here anyway; recording what came back is free."""

    def _stripe_sub(self, mocker, item_id="si_1", period_end=1_792_000_000):
        line = mocker.Mock(id=item_id, current_period_end=period_end)
        line.price = {"id": "squarelet_plan_test"}
        return mocker.Mock(
            id="sub_here",
            status="active",
            items=mocker.Mock(data=[line]),
            **{
                "__getitem__": lambda self, key: {
                    "items": mocker.Mock(data=[line]),
                    "collection_method": "charge_automatically",
                }[key]
            },
        )

    def test_a_subscription_with_no_cached_date_is_visited(
        self, subscription_item_factory, mocker
    ):
        """Even when every line already has its id."""
        item = subscription_item_factory(
            subscription__subscription_id="sub_here",
            subscription__current_period_end=None,
            stripe_item_id="si_1",
        )
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            new_callable=mocker.PropertyMock,
            return_value=self._stripe_sub(mocker),
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_stripe_item_ids")
        out = StringIO()

        call_command("backfill_stripe_item_ids", stdout=out)

        item.subscription.refresh_from_db()
        assert item.subscription.current_period_end is not None
        assert "filled: 1" in out.getvalue()
