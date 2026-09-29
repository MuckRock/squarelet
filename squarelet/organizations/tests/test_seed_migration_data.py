"""The seed exists to rehearse release 5, so its test is the rehearsal."""

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


def line_for(out, org):
    return out.split(f"{org}: ")[1].split("\n")[0]


@pytest.fixture(name="consolidated")
def consolidated_fixture(mocker):
    """Seeded, with the prices consolidation would create, and no Stripe."""
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


@pytest.mark.django_db()
class TestTheSeed:
    def test_it_seeds_every_shape_once(self):
        run("seed_migration_data")
        run("seed_migration_data")

        orgs = Organization.objects.filter(slug__startswith="mig-", individual=False)
        assert orgs.count() == len({org for org, *_ in SUBSCRIBERS})
        assert SubscriptionItem.objects.filter(
            subscription__organization__in=orgs
        ).count() == len(SUBSCRIBERS)

    def test_teardown_removes_it(self):
        run("seed_migration_data")
        run("seed_migration_data", teardown=True)

        assert not Organization.objects.filter(
            slug__startswith="mig-", individual=False
        ).exists()


@pytest.mark.django_db()
@pytest.mark.usefixtures("consolidated")
class TestTheRehearsal:
    def test_the_dry_run_refuses_nobody(self):
        out = run(
            "backfill_plan_prices", dry_run=True, local_only=True, actor="mig-actor"
        )

        refused = [text for text in out.split("\n") if text.strip().startswith("!")]
        assert not refused, refused
        assert f"{len(SUBSCRIBERS)} migrated, 0 already done, 0 deferred" in out
        assert "+ 13 x muckrock-request-pack" in line_for(out, "mig-org-18")
        assert "+ 200 x muckrock-request-pack" in line_for(out, "mig-flexible")
        assert "pack" not in line_for(out, "mig-org-min")
        assert "Nonprofit" in line_for(out, "mig-nonprofit")
        for org in ("mig-crp-a", "mig-crp-b"):
            assert "custom-crp -> Organization" in line_for(out, org)

    def test_a_real_run_then_a_rerun(self):
        first = run("backfill_plan_prices", local_only=True, actor="mig-actor")

        assert f"{len(SUBSCRIBERS)} migrated" in first
        assert "still without a price: 0 deferred, 0 unexpected" in first
        assert "still above quantity 1" not in first
        cohort = {
            item.subscription.organization.slug: item.plan_price.interval
            for item in SubscriptionItem.objects.filter(
                plan_price__code="election-cohort"
            ).select_related("subscription__organization", "plan_price")
        }
        assert cohort == {
            "mig-cohort-active": "annual",
            "mig-cohort-leaving": "annual",
            "mig-cohort-monthly": "monthly",
        }
        beta = SubscriptionItem.objects.get(subscription__organization__slug="mig-beta")
        assert beta.subscription.kind == "free"
        assert beta.granted_reason.startswith("Migrated from legacy")

        before = set(
            SubscriptionItem.objects.values_list(
                "pk", "plan_id", "plan_price_id", "quantity", "subscription_id"
            )
        )
        second = run("backfill_plan_prices", local_only=True, actor="mig-actor")
        after = set(
            SubscriptionItem.objects.values_list(
                "pk", "plan_id", "plan_price_id", "quantity", "subscription_id"
            )
        )

        assert before == after, "a re-run changes nothing"
        assert f"0 migrated, {len(SUBSCRIBERS)} already done" in second
