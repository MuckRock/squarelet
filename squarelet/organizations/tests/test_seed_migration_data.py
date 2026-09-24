"""The manufactured-data seed for rehearsing release 5.

It exists so the migration can be rehearsed on a review app with no
production data.  So the test is the rehearsal: seed, consolidate, dry-run,
and the dry run must not abort and must not refuse anyone.
"""

# Django
from django.core.management import call_command

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.management.commands.seed_migration_data import SUBSCRIBERS
from squarelet.organizations.models import Organization, SubscriptionItem


def run(command, **kwargs):
    out = StringIO()
    call_command(command, stdout=out, stderr=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db()
class TestTheSeedRehearsesTheMigration:
    def test_it_seeds_every_shape(self):
        run("seed_migration_data")

        orgs = Organization.objects.filter(slug__startswith="mig-", individual=False)
        assert orgs.count() == len({org for org, *_ in SUBSCRIBERS})
        assert SubscriptionItem.objects.filter(
            subscription__organization__in=orgs
        ).count() == len(SUBSCRIBERS)

    def test_it_is_idempotent(self):
        run("seed_migration_data")
        run("seed_migration_data")

        orgs = Organization.objects.filter(slug__startswith="mig-")
        assert SubscriptionItem.objects.filter(
            subscription__organization__in=orgs
        ).count() == len(SUBSCRIBERS)

    def test_the_dry_run_passes_preflight_and_refuses_nobody(self, mocker):
        """The whole point: every shape the command has a branch for, and
        every one of them migrates cleanly or is deferred on purpose."""
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )
        run("seed_migration_data")
        # The real consolidation creates Stripe Products and Prices.  Here
        # the PlanPrice rows are what matter, so create them the way the
        # command would and skip Stripe.
        mocker.patch(
            "squarelet.organizations.models.payment.Plan.ensure_stripe_product",
            return_value="prod_mig",
        )
        mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price",
            return_value="price_mig",
        )
        run("consolidate_stripe_products", allow_missing=True)

        out = run(
            "backfill_plan_prices", dry_run=True, local_only=True, actor="mig-actor"
        )

        refused = [line for line in out.split("\n") if line.strip().startswith("!")]
        assert not refused, refused
        assert "21 migrated, 0 deferred, 0 failed" in out
        # DocumentCloud Premium at quantity 1: no blocks, no pack, same grant.
        dc = out.split("mig-dc-premium: ")[1].split("\n")[0]
        assert "documentcloud-premium -> DocumentCloud Premium" in dc
        assert "pack" not in dc
        # Nothing is deferred any more: the cohort has a coded price at
        # both cadences, and that was the last slug in the set.
        assert " deferred\n" not in out, "no line should be left alone now"
        cohort = [line for line in out.split("\n") if "election-accountability" in line]
        assert len(cohort) == 3, cohort
        assert any("Annual, Standard, election-cohort" in line for line in cohort)
        assert any("Monthly, Standard, election-cohort" in line for line in cohort)
        # Decomposed: the block-holders each gain a pack.
        assert "mig-org-18: organization -> " in out
        assert "18" not in out.split("mig-org-18")[1].split("\n")[0].split("x")[0]
        assert "+ 13 x muckrock-request-pack" in out  # 18 - 5
        assert "+ 200 x muckrock-request-pack" in out  # flexible users
        # On minimum: no pack.
        min_line = out.split("mig-org-min: ")[1].split("\n")[0]
        assert "muckrock-request-pack" not in min_line
        # Both CRP orgs to standard Organization, no pack.
        for org in ("mig-crp-a", "mig-crp-b"):
            line = out.split(f"{org}: ")[1].split("\n")[0]
            assert "custom-crp -> Organization (Monthly, Standard)" in line
            assert "pack" not in line
        # The nonprofit lands on the nonprofit price.
        assert "(Annual, Nonprofit)" in out.split("mig-nonprofit: ")[1].split("\n")[0]

    def test_a_real_run_then_a_rerun(self, mocker):
        """What the review-app rehearsal looks like after the dry run.

        The dry run never reaches `_write`, so it exercises neither the
        line-identity fix nor the re-run guard.  A real local-only run
        does the first; running it again does the second, and is the case
        that used to reprice nonprofits.
        """
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )
        mocker.patch(
            "squarelet.organizations.models.payment.Plan.ensure_stripe_product",
            return_value="prod_mig",
        )
        mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price",
            return_value="price_mig",
        )
        run("seed_migration_data")
        run("consolidate_stripe_products", allow_missing=True)

        first = run("backfill_plan_prices", local_only=True, actor="mig-actor")

        assert "21 migrated, 0 deferred, 0 failed" in first
        # The post-run reports now describe a database the run changed.
        assert "0 deferred by choice, 0 unexpected" in first
        # Nothing is left above quantity 1 at all, which is what the
        # entitlement shape migration refuses on.  The cohort lines were
        # the last holdouts and they now hold a price of their own.
        assert "still above quantity 1" not in first, first
        # Each cohort line at the cadence its own subscription bills,
        # which the mapping cannot express and the money check cannot see.
        cohort = {
            item.subscription.organization.slug: item.plan_price.interval
            for item in SubscriptionItem.objects.select_related(
                "subscription__organization", "plan_price"
            ).filter(plan_price__code="election-cohort")
        }
        assert cohort == {
            "mig-cohort-active": "annual",
            "mig-cohort-leaving": "annual",
            "mig-cohort-monthly": "monthly",
        }, cohort
        # Two lines now: the base at 1 and the pack beside it.
        big = SubscriptionItem.objects.get(
            subscription__organization__slug="mig-org-18", plan__slug="organization"
        )
        assert big.quantity == 1
        pack = SubscriptionItem.objects.get(
            subscription__organization__slug="mig-org-18",
            plan__slug="muckrock-request-pack",
        )
        assert pack.quantity == 13
        nonprofit = SubscriptionItem.objects.get(
            subscription__organization__slug="mig-nonprofit"
        )
        assert nonprofit.plan_price.label == "nonprofit"
        comped = SubscriptionItem.objects.get(
            subscription__organization__slug="mig-beta"
        )
        assert comped.granted_reason.startswith("Migrated from legacy")

        before = set(
            SubscriptionItem.objects.values_list(
                "pk", "plan_id", "plan_price_id", "quantity"
            )
        )
        second = run("backfill_plan_prices", local_only=True, actor="mig-actor")
        after = set(
            SubscriptionItem.objects.values_list(
                "pk", "plan_id", "plan_price_id", "quantity"
            )
        )

        assert before == after, "a re-run changes nothing"
        assert "already on" in second
        nonprofit.refresh_from_db()
        assert nonprofit.plan_price.label == "nonprofit", "still the deal they had"

    def test_teardown_removes_it(self):
        run("seed_migration_data")
        run("seed_migration_data", teardown=True)

        assert not Organization.objects.filter(
            slug__startswith="mig-", individual=False
        ).exists()
