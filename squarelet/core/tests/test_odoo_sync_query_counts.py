# Django
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

# Standard Library
from unittest.mock import patch

# Third Party
import pytest

# Squarelet
from squarelet.core.management.commands import sync_odoo
from squarelet.organizations.tests.factories import OrganizationFactory, PlanFactory
from squarelet.users.tests.factories import UserFactory

# pylint:disable=protected-access


def _fake_odoo(endpoint, payload):  # pylint:disable=unused-argument
    """Fake Odoo where nothing exists yet and every create succeeds."""
    if endpoint.endswith("/search_read"):
        return []
    if endpoint.endswith("/create"):
        return [1]
    return True


def _sync_query_count():
    """Run a full live sync against the fake Odoo; return the Django query count."""
    sync_odoo._PLAN_ID_CACHE.clear()
    with patch.object(sync_odoo, "_odoo_request", side_effect=_fake_odoo):
        with CaptureQueriesContext(connection) as ctx:
            sync_odoo._run_sync(dry_run=False, remove_members=False, slug=None)
    return len(ctx.captured_queries)


def _add_members(org, count):
    for _ in range(count):
        org.memberships.create(user=UserFactory())


@pytest.mark.django_db
class TestQueryCounts:
    """Sync query count must not grow with orgs, members, or collaborative members."""

    def test_flat_as_orgs_grow(self):
        """More Sunlight orgs add no queries."""
        plan = PlanFactory(name="Sunlight QC Orgs", wix=True)
        _add_members(OrganizationFactory(plans=[plan]), 1)
        baseline = _sync_query_count()

        for _ in range(4):
            _add_members(OrganizationFactory(plans=[plan]), 1)
        assert _sync_query_count() == baseline

    def test_flat_as_members_grow(self):
        """More members in an org add no queries."""
        plan = PlanFactory(name="Sunlight QC Members", wix=True)
        org = OrganizationFactory(plans=[plan])
        _add_members(org, 1)
        baseline = _sync_query_count()

        _add_members(org, 5)
        assert _sync_query_count() == baseline

    @override_settings(COLLABORATIVE_TAGS={"collab-qc": 9})
    def test_flat_as_collaborative_members_grow(self):
        """More collaborative member orgs add no queries."""
        plan = PlanFactory(name="Collab QC", wix=True)
        collab = OrganizationFactory(
            name="collab-qc",
            slug="collab-qc",
            plans=[plan],
            collective_enabled=True,
        )
        collab.members.add(OrganizationFactory())
        baseline = _sync_query_count()

        for _ in range(4):
            collab.members.add(OrganizationFactory())
        assert _sync_query_count() == baseline

    def test_fixed_query_budget(self, django_assert_num_queries):
        """Pin the total for one Sunlight org with two members."""
        plan = PlanFactory(name="Sunlight QC Budget", wix=True)
        _add_members(OrganizationFactory(plans=[plan]), 2)
        with patch.object(sync_odoo, "_odoo_request", side_effect=_fake_odoo):
            with django_assert_num_queries(10):
                sync_odoo._run_sync(dry_run=False, remove_members=False, slug=None)
