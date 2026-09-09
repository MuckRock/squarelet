"""Tests for data migrations.

Migrations run once, on production, with no way to try again - so the ones
that move data are worth exercising against real rows rather than reasoning
about.  These roll the schema back to just before the migration under test,
build the rows it will find, and roll forward.
"""

# Historical models come back from `apps.get_model` as classes, and are named
# like classes.
# pylint: disable=invalid-name

# Django
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader

# Third Party
import pytest

APP = "organizations"
# The migration under test, found by name rather than by number: the squash
# further up the stack renumbers it and removes the one it currently depends
# on, so anything pinned here would break on rebase.
UNDER_TEST = "subscription_parent"


def _bracket():
    """Return the migration under test and the one immediately before it."""
    loader = MigrationLoader(connection)
    target = next(
        name
        for app, name in loader.graph.nodes
        if app == APP and name.endswith(UNDER_TEST)
    )
    before = next(
        name
        for app, name in loader.graph.node_map[(APP, target)].parents
        if app == APP
    )
    return before, target


def migrate_to(target):
    """Run the organizations app to `target` and return its model registry."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def migrate_to_latest():
    """Put the app back at its newest migration, whatever that is.

    Not the migration under test: branches above this one add migrations
    after it, and leaving the schema short of them would break every test
    that ran afterwards.
    """
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes(APP))


@pytest.mark.django_db(transaction=True)
class TestAdoptItemsIntoSubscriptions:
    """0085 gives every subscription line a parent, one per billing shape."""

    @pytest.fixture(autouse=True)
    def _leave_the_database_migrated(self):
        """Put the schema back for whatever runs next.

        The rows go first: a test that deliberately leaves data 0085 refuses
        would otherwise be refused again on the way back up, and every test
        after it would run against the wrong schema.
        """
        yield
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM organizations_subscriptionitem")
        migrate_to_latest()

    @staticmethod
    def _organization(apps, name):
        Organization = apps.get_model(APP, "Organization")
        return Organization.objects.create(name=name, slug=name.lower())

    @staticmethod
    def _plan(apps, name, annual=False):
        Plan = apps.get_model(APP, "Plan")
        return Plan.objects.create(name=name, slug=name.lower(), annual=annual)

    def test_lines_of_one_shape_share_a_parent(self):
        """The point of the split: two monthly lines, one Stripe subscription."""
        old = migrate_to(_bracket()[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Shared")
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "Paid"),
            subscription_id="sub_shared",
        )
        # Comped lines never reached Stripe, so they carry no id.  The old
        # schema made `subscription_id` unique, which is why a group can hold
        # at most one line that names a Stripe subscription.
        SubscriptionItem.objects.create(
            organization=organization, plan=self._plan(old, "Comped")
        )

        new = migrate_to(_bracket()[1])

        Subscription = new.get_model(APP, "Subscription")
        subscriptions = Subscription.objects.filter(organization=organization.pk)
        assert subscriptions.count() == 1
        assert subscriptions.first().items.count() == 2
        assert subscriptions.first().subscription_id == "sub_shared"

    def test_a_different_shape_gets_its_own_parent(self):
        """Stripe cannot bill monthly and annual on one subscription."""
        old = migrate_to(_bracket()[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Mixed")
        SubscriptionItem.objects.create(
            organization=organization, plan=self._plan(old, "Monthly")
        )
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "Yearly", annual=True),
        )

        new = migrate_to(_bracket()[1])

        Subscription = new.get_model(APP, "Subscription")
        shapes = set(
            Subscription.objects.filter(organization=organization.pk).values_list(
                "interval", "collection_method"
            )
        )
        assert shapes == {
            ("monthly", "charge_automatically"),
            ("annual", "send_invoice"),
        }

    def test_two_stripe_subscriptions_of_one_shape_are_refused(self):
        """One row holds one Stripe id, so merging would orphan the other."""
        old = migrate_to(_bracket()[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Doubled")
        for plan_name, stripe_id in (("A", "sub_a"), ("B", "sub_b")):
            SubscriptionItem.objects.create(
                organization=organization,
                plan=self._plan(old, plan_name),
                subscription_id=stripe_id,
            )

        with pytest.raises(Exception, match="more than one"):
            migrate_to(_bracket()[1])

    def test_a_parent_stops_only_when_every_line_has(self):
        """One cancelled line among several is that line's own business."""
        old = migrate_to(_bracket()[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Partly")
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "Staying"),
            subscription_id="sub_partly",
            cancelled=False,
        )
        SubscriptionItem.objects.create(
            organization=organization, plan=self._plan(old, "Going"), cancelled=True
        )

        new = migrate_to(_bracket()[1])

        Subscription = new.get_model(APP, "Subscription")
        subscription = Subscription.objects.get(organization=organization.pk)
        assert not subscription.cancelled
