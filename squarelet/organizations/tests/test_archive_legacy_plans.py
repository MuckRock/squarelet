# Django
from django.core.management import call_command

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.management.commands.archive_legacy_plans import (
    canonical_slugs,
)
from squarelet.organizations.models import Plan
from squarelet.organizations.tests.factories import (
    OrganizationFactory,
    PlanFactory,
    PlanPriceFactory,
    SubscriptionItemFactory,
)


def run(**kwargs):
    out = StringIO()
    call_command("archive_legacy_plans", stdout=out, **kwargs)
    return out.getvalue()


def legacy_plan(name="Dead Plan", slug="dead-plan"):
    """A plan the consolidation has moved everyone off."""
    return PlanFactory(name=name, slug=slug)


def plan_with_slug(name, slug):
    """One row per slug, seeded or not.

    The factory on a seeded slug makes `<slug>-2`, which nothing maps.
    """
    existing = Plan.objects.including_archived().filter(slug=slug).first()
    if existing is not None:
        existing.archived = False
        existing.save(update_fields=["archived"])
        existing.prices.all().delete()
        return existing
    return PlanFactory(name=name, slug=slug)


@pytest.mark.django_db()
class TestWhatGetsArchived:
    def test_an_unused_legacy_plan_is_archived(self):
        plan = legacy_plan()

        run()

        plan.refresh_from_db()
        assert plan.archived

    def test_the_row_survives(self):
        """The change log references it; the history is the point."""
        plan = legacy_plan()

        run()

        # Hidden, but kept for the change log.
        assert not Plan.objects.filter(pk=plan.pk).exists()
        assert Plan.objects.including_archived().filter(pk=plan.pk).exists()

    def test_a_canonical_plan_is_untouched(self):
        slug = sorted(canonical_slugs())[0]
        # The seeded row, not a `<slug>-2` that would be archived.
        plan = Plan.objects.filter(slug=slug).first() or PlanFactory(
            name=f"Canonical {slug}", slug=slug
        )

        run()

        plan.refresh_from_db()
        assert not plan.archived

    def test_a_plan_with_an_active_price_is_left_alone(self):
        plan = legacy_plan()
        PlanPriceFactory(plan=plan, active=True)

        out = run()

        plan.refresh_from_db()
        assert not plan.archived
        assert "still in use" in out

    def test_a_plan_with_a_live_line_is_left_alone(self):
        plan = legacy_plan()
        SubscriptionItemFactory(plan=plan, subscription__cancelled=False)

        run()

        plan.refresh_from_db()
        assert not plan.archived


@pytest.mark.django_db()
class TestEntryRowsAreKeptWhilePurchasesGoThroughThem:
    """`sunlight-essential-annual` holds no price, but purchases resolve through it."""

    def test_an_entry_row_whose_target_is_priced_is_kept(self):
        canonical = plan_with_slug("Sunlight Essential", "sunlight-essential")
        PlanPriceFactory(plan=canonical, interval="annual", label="standard")
        entry = plan_with_slug(
            "Sunlight Essential (Annual)", "sunlight-essential-annual"
        )

        out = run()

        entry.refresh_from_db()
        assert not entry.archived
        assert "sunlight-essential-annual: still in use" in out
        assert "still purchasable" in out

    def test_an_entry_row_whose_target_has_no_price_is_archived(self):
        """Nothing to resolve to, so nothing can be bought through it."""
        plan_with_slug("Sunlight Essential", "sunlight-essential")
        entry = plan_with_slug(
            "Sunlight Essential (Annual)", "sunlight-essential-annual"
        )

        run()

        entry.refresh_from_db()
        assert entry.archived


@pytest.mark.django_db()
class TestEveryCanonicalPlanIsKept:
    """The price matrix, not the mapping's targets, which miss some."""

    @pytest.mark.parametrize(
        "slug",
        [
            "documentcloud-credit-pack",
            "scoutpost-credit-pack",
            "documentcloud-premium",
            "scoutpost-pro",
            "scoutpost-team",
        ],
    )
    def test_a_canonical_plan_with_no_price_yet_is_still_kept(self, slug):
        """As on any environment where this runs before consolidation."""
        plan = plan_with_slug(f"Canonical {slug}", slug)

        out = run()

        plan.refresh_from_db()
        assert not plan.archived, f"{slug} is in the price matrix"
        # Per plan, not by the counts, which depend on what else is seeded.
        assert f"{slug}: still in use" not in out
        assert canonical_slugs() >= {slug}


@pytest.mark.django_db()
class TestACancelledLineStillBlocksIt:
    """A cancelled line is served until `cancel_at` and can resubscribe."""

    def test_a_plan_with_only_a_cancelled_line_is_left_alone(self):
        plan = legacy_plan()
        SubscriptionItemFactory(plan=plan, subscription__cancelled=True)

        out = run()

        plan.refresh_from_db()
        assert not plan.archived
        assert "still in use (1 line(s)" in out

    def test_once_the_sweep_has_removed_it_the_plan_is_archived(self):
        plan = legacy_plan()
        item = SubscriptionItemFactory(plan=plan, subscription__cancelled=True)
        item.delete()  # what restore_organization does when cancel_at arrives

        run()

        plan.refresh_from_db()
        assert plan.archived


@pytest.mark.django_db()
class TestArchivedPlansAreNotOffered:
    """`Plan.objects` hides them; these test the real surfaces customers use."""

    def test_the_default_manager_hides_it(self):
        PlanFactory(name="Retired", slug="retired", public=True, archived=True)

        assert not Plan.objects.filter(slug="retired").exists()
        assert Plan.objects.including_archived().filter(slug="retired").exists()

    def test_the_sign_up_form_does_not_offer_it(self):
        """`Plan.objects.filter(public=True)` - the sign-up form's queryset."""
        PlanFactory(name="Retired", slug="retired", public=True, archived=True)

        assert not Plan.objects.filter(public=True).filter(slug="retired").exists()

    def test_it_cannot_be_fetched_by_slug_to_buy(self):
        """The purchase view's `Plan.objects.get(slug=...)`."""
        PlanFactory(name="Retired", slug="retired", public=True, archived=True)

        with pytest.raises(Plan.DoesNotExist):
            Plan.objects.get(slug="retired")

    def test_an_organization_on_it_still_resolves_its_own_plan(self):
        """Retired for new buyers, not vanished from the people on it."""
        item = SubscriptionItemFactory(
            plan=PlanFactory(name="Retired", slug="retired", archived=True)
        )

        assert item.plan in item.subscription.organization.get_plans()

    def test_an_archived_plan_is_not_a_choice(self):
        organization = OrganizationFactory(individual=False)
        plan = PlanFactory(name="Retired", slug="retired", public=True, archived=True)

        assert plan not in Plan.objects.choices(organization)

    def test_even_for_an_organization_currently_on_it(self):
        """`choices()` also matches the organization's own plans; not this one."""
        item = SubscriptionItemFactory(
            plan=PlanFactory(name="Retired", slug="retired", archived=True)
        )
        organization = item.subscription.organization

        assert item.plan not in Plan.objects.choices(organization)


@pytest.mark.django_db()
class TestReporting:
    def test_dry_run_writes_nothing(self):
        plan = legacy_plan()

        run(dry_run=True)

        plan.refresh_from_db()
        assert not plan.archived

    def test_running_twice_is_quiet_the_second_time(self):
        plan = legacy_plan()

        run()
        out = run()

        plan.refresh_from_db()
        assert plan.archived
        # Counted, not named: a seeded database has legacy plans of its own
        # that the first run archives too.
        assert "0 archived," in out
