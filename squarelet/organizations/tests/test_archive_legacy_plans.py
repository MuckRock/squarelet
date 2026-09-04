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

        assert Plan.objects.filter(pk=plan.pk).exists()

    def test_a_canonical_plan_is_untouched(self):
        slug = sorted(canonical_slugs())[0]
        plan = PlanFactory(name=f"Canonical {slug}", slug=slug)

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
class TestCancelledLinesDoNotBlockIt:
    """They are the record of what someone used to be on.

    Deleting the plan would have taken them with it - SubscriptionItem.plan
    is CASCADE - which is one of the reasons this archives instead.  A flag
    lets them keep pointing at it quite happily.
    """

    def test_a_plan_with_only_cancelled_lines_is_archived(self):
        plan = legacy_plan()
        SubscriptionItemFactory(plan=plan, cancelled=True)

        run()

        plan.refresh_from_db()
        assert plan.archived

    def test_the_cancelled_line_survives(self):
        plan = legacy_plan()
        item = SubscriptionItemFactory(plan=plan, cancelled=True)

        run()

        assert type(item).objects.filter(pk=item.pk).exists()

    def test_they_are_counted_in_the_report(self):
        plan = legacy_plan()
        SubscriptionItemFactory(plan=plan, cancelled=True)

        assert "keeps 1 cancelled line" in run()


@pytest.mark.django_db()
class TestArchivedPlansAreNotOffered:
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
        legacy_plan()

        run()
        out = run()

        assert "1 already archived" in out
