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
