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

        # Hidden from the default manager, which is the point of archiving -
        # but the row is there for the change log to reference.
        assert not Plan.objects.filter(pk=plan.pk).exists()
        assert Plan.objects.including_archived().filter(pk=plan.pk).exists()

    def test_a_canonical_plan_is_untouched(self):
        slug = sorted(canonical_slugs())[0]
        # Adopt the seeded row: PlanFactory get-or-creates on *name* and
        # `slug` is an AutoSlugField, so asking for a slug the seeded data
        # already holds yields `<slug>-2` - which is not canonical, and
        # would be archived.
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
        SubscriptionItemFactory(plan=plan, cancelled=False)

        run()

        plan.refresh_from_db()
        assert not plan.archived


@pytest.mark.django_db()
class TestACancelledLineStillBlocksIt:
    """A cancelled line is a subscriber leaving, not one who has left.

    It still bills and still grants access until `cancel_at`, and its
    subscriber can press Resubscribe and be live again.  This used to
    archive a plan with only cancelled lines on it, which left one Sunlight
    subscriber renewing on an archived plan.  The sweep deletes the line
    when the date arrives; the plan becomes archivable on the run after.
    """

    def test_a_plan_with_only_a_cancelled_line_is_left_alone(self):
        plan = legacy_plan()
        SubscriptionItemFactory(plan=plan, cancelled=True)

        out = run()

        plan.refresh_from_db()
        assert not plan.archived
        assert "still in use (1 line(s)" in out

    def test_once_the_sweep_has_removed_it_the_plan_is_archived(self):
        plan = legacy_plan()
        item = SubscriptionItemFactory(plan=plan, cancelled=True)
        item.delete()  # what restore_organization does when cancel_at arrives

        run()

        plan.refresh_from_db()
        assert plan.archived


@pytest.mark.django_db()
class TestArchivedPlansAreNotOffered:
    """`Plan.objects` hides them, so every surface is safe by default.

    Before the manager did this, the only place reading the flag was
    `choices()`, whose one caller is a template tag no template invokes -
    and the sign-up form, the Sunlight listings and purchase-by-slug all
    queried `Plan.objects` directly.  Archiving changed nothing a customer
    could see.  These test the real surfaces, not the tag.
    """

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
        """A retired plan is retired for renewals too.

        `choices()` also matches on the organization's own subscriptions,
        which would otherwise offer the plan back to exactly the people
        being moved off it.
        """
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
