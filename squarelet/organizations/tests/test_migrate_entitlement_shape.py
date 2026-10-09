# Django
from django.core.management import call_command
from django.core.management.base import CommandError

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.entitlement_shape import grant_new, grant_old, reshape
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    PlanFactory,
    SubscriptionItemFactory,
)

TIER = {"base_requests": 50, "minimum_users": 5, "requests_per_user": 10}
PACK = {"base_requests": 0, "minimum_users": 0, "requests_per_user": 10}


def run(**kwargs):
    out = StringIO()
    call_command("migrate_entitlement_shape", stdout=out, **kwargs)
    return out.getvalue()


def plan_named(name, slug):
    """One Plan per name, at exactly `slug`.

    The factory gets-or-creates on name, so a second name for one slug would
    land at `<slug>-2`, a plan nobody subscribes to.
    """
    return PlanFactory(name=name, slug=slug)


ORG_PLAN = ("Organization", "organization")
PACK_PLAN = ("MuckRock Request Pack", "muckrock-request-pack")


def tier_entitlement(resources=None):
    entitlement = EntitlementFactory(resources=dict(resources or TIER))
    entitlement.plans.add(plan_named(*ORG_PLAN))
    return entitlement


def pack_entitlement(resources=None):
    entitlement = EntitlementFactory(resources=dict(resources or PACK))
    entitlement.plans.add(plan_named(*PACK_PLAN))
    return entitlement


class TestTheTwoFormulasAgree:
    """`base + max(q - 1, 0) * base` is `base * q` for every q >= 1."""

    @pytest.mark.parametrize("quantity", [1, 2, 5, 25, 100])
    def test_a_reshaped_tier_reads_the_same_both_ways(self, quantity):
        target = reshape(TIER, is_pack=False)
        assert grant_old(target, quantity) == grant_new(target, quantity)

    @pytest.mark.parametrize("quantity", [1, 2, 5, 25, 100])
    def test_a_reshaped_pack_reads_the_same_both_ways(self, quantity):
        target = reshape(PACK, is_pack=True)
        assert grant_old(target, quantity) == grant_new(target, quantity)

    def test_a_tier_at_quantity_one_keeps_its_grant(self):
        assert grant_old(TIER, 1) == grant_old(reshape(TIER, is_pack=False), 1) == 50

    def test_a_pack_keeps_its_grant_at_any_quantity(self):
        target = reshape(PACK, is_pack=True)
        assert grant_old(PACK, 25) == grant_old(target, 25) == 250

    def test_a_decomposed_subscriber_is_whole(self):
        """A tier at 1 plus 25 blocks, as the pricing migration leaves it."""
        tier = reshape(TIER, is_pack=False)
        pack = reshape(PACK, is_pack=True)

        assert grant_old(TIER, 30) == 300
        assert grant_old(tier, 1) + grant_old(pack, 25) == 300
        assert grant_new(tier, 1) + grant_new(pack, 25) == 300

    def test_the_pack_transform_is_not_the_tier_transform(self):
        """A pack's value is in `per_user`; the tier transform would zero it."""
        wrong = reshape(PACK, is_pack=False)
        assert grant_new(wrong, 25) == 0
        assert grant_new(reshape(PACK, is_pack=True), 25) == 250


class TestWhatIsLeftAlone:
    def test_resources_that_do_not_scale_are_untouched(self):
        """Sunlight research hours buy no more with more blocks."""
        hours = {"monthly_research_hours": 50}
        assert reshape(hours, is_pack=False) == hours

    def test_unrelated_keys_survive(self):
        resources = dict(TIER, feature_level=2)
        assert reshape(resources, is_pack=False)["feature_level"] == 2


@pytest.mark.django_db()
class TestPreflight:
    """The transform is exact at quantity 1 and nowhere else."""

    def test_a_tier_line_above_one_aborts(self):
        tier_entitlement()
        SubscriptionItemFactory(plan=plan_named(*ORG_PLAN), quantity=30)

        with pytest.raises(CommandError, match="not at quantity 1"):
            run()

    def test_the_offending_line_is_named(self):
        tier_entitlement()
        item = SubscriptionItemFactory(plan=plan_named(*ORG_PLAN), quantity=30)

        with pytest.raises(CommandError) as excinfo:
            run()

        assert item.subscription.organization.slug in str(excinfo.value)

    def test_nothing_is_written_when_it_aborts(self):
        entitlement = tier_entitlement()
        SubscriptionItemFactory(plan=plan_named(*ORG_PLAN), quantity=30)

        with pytest.raises(CommandError):
            run()

        entitlement.refresh_from_db()
        assert entitlement.resources == TIER

    def test_a_pack_line_above_one_is_fine(self):
        """`base * q` is exactly what a pack is supposed to mean."""
        pack_entitlement()
        SubscriptionItemFactory(
            plan=plan_named(*PACK_PLAN),
            quantity=25,
        )

        run()  # does not raise

    def test_a_line_on_a_plan_that_does_not_scale_is_fine_at_any_quantity(self):
        """A flat entitlement grants the same at any quantity."""
        # Not "professional": an earlier module may have seeded it scaling.
        flat = plan_named("Flat Per-Unit Plan", "flat-per-unit")
        entitlement = EntitlementFactory(resources={"base_requests": 20})
        entitlement.plans.add(flat)
        SubscriptionItemFactory(plan=flat, quantity=3)

        run()  # does not raise

        entitlement.refresh_from_db()
        assert entitlement.resources == {"base_requests": 20}, "left alone"

    def test_an_entitlement_on_both_a_pack_and_a_tier_aborts(self):
        entitlement = tier_entitlement()
        entitlement.plans.add(plan_named(*PACK_PLAN))

        with pytest.raises(CommandError, match="both a pack plan and a tier"):
            run()


@pytest.mark.django_db()
class TestTheRun:
    def test_a_tier_is_reshaped(self):
        entitlement = tier_entitlement()

        run()

        entitlement.refresh_from_db()
        assert entitlement.resources == {
            "base_requests": 50,
            "minimum_users": 1,
            "requests_per_user": 50,
        }

    # Every pack 0082 seeds, with its real shape, including those no legacy
    # plan decomposes into.
    @pytest.mark.parametrize(
        ("name", "slug", "resource_key", "per_unit"),
        [
            ("MuckRock Request Pack", "muckrock-request-pack", "requests", 10),
            (
                "DocumentCloud Credit Pack",
                "documentcloud-credit-pack",
                "ai_credits",
                500,
            ),
            ("Scoutpost Credit Pack", "scoutpost-credit-pack", "credits", 1000),
        ],
    )
    def test_every_pack_is_reshaped_the_other_way(
        self, name, slug, resource_key, per_unit
    ):
        entitlement = EntitlementFactory(
            resources={
                f"base_{resource_key}": 0,
                "minimum_users": 0,
                f"{resource_key}_per_user": per_unit,
            }
        )
        entitlement.plans.add(plan_named(name, slug))

        run()

        entitlement.refresh_from_db()
        assert entitlement.resources == {
            f"base_{resource_key}": per_unit,
            "minimum_users": 1,
            f"{resource_key}_per_user": per_unit,
        }, f"{slug} must keep its per-unit value, not have it zeroed"
        assert grant_new(entitlement.resources, 25) == 25 * per_unit

    def test_a_reshape_that_would_change_a_grant_aborts_and_rolls_back(self):
        """`minimum_users: 0` with a rate changes at quantity 1, held or not.

        The run is one transaction, so the entitlement reshaped before it
        rolls back too.
        """
        fine = tier_entitlement()
        broken = EntitlementFactory(
            resources={"base_requests": 50, "minimum_users": 0, "requests_per_user": 10}
        )
        broken.plans.add(plan_named("Zero Minimum", "zero-minimum"))

        with pytest.raises(CommandError, match="would change the grant at quantity 1"):
            run()

        fine.refresh_from_db()
        broken.refresh_from_db()
        assert fine.resources == TIER, "rolled back with the rest"
        assert broken.resources["requests_per_user"] == 10

    def test_every_grant_that_would_change_is_named_in_one_run(self):
        """So one production dry run finds them all."""
        for slug in ("zero-minimum-a", "zero-minimum-b"):
            entitlement = EntitlementFactory(
                resources={
                    "base_requests": 50,
                    "minimum_users": 0,
                    "requests_per_user": 10,
                }
            )
            entitlement.plans.add(plan_named(slug, slug))

        with pytest.raises(CommandError) as raised:
            run(dry_run=True)

        assert str(raised.value).count("would change the grant") == 2

    def test_a_change_hidden_in_the_total_aborts(self, mocker):
        """One resource up and another down by as much still changes both."""
        two = {
            "base_requests": 50,
            "requests_per_user": 50,
            "base_ai_credits": 500,
            "ai_credits_per_user": 500,
            "minimum_users": 1,
        }
        tier_entitlement(two)
        mocker.patch(
            "squarelet.organizations.management.commands."
            "migrate_entitlement_shape.reshape",
            return_value=dict(
                two,
                base_requests=60,
                requests_per_user=60,
                base_ai_credits=490,
                ai_credits_per_user=490,
            ),
        )

        with pytest.raises(CommandError, match="would change the grant"):
            run()

    def test_dry_run_writes_nothing(self):
        entitlement = tier_entitlement()

        run(dry_run=True)

        entitlement.refresh_from_db()
        assert entitlement.resources == TIER

    def test_running_twice_changes_nothing(self):
        entitlement = tier_entitlement()

        run()
        entitlement.refresh_from_db()
        once = dict(entitlement.resources)
        run()
        entitlement.refresh_from_db()

        assert entitlement.resources == once

    def test_the_second_run_reports_no_work(self):
        tier_entitlement()

        run()
        out = run()

        assert "already in shape" in out

    def test_the_arithmetic_is_printed(self):
        """The point of the step is the numbers, so show them."""
        tier_entitlement()
        SubscriptionItemFactory(plan=plan_named(*ORG_PLAN), quantity=1)

        out = run(dry_run=True)

        assert (
            "quantity 1: 50 requests today, 50 requests under the old formula, "
            "50 requests under the new" in out
        )
        assert "CHANGED" not in out
