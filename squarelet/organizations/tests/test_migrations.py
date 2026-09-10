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
from django.utils.text import slugify

# Standard Library
from datetime import date

# Standard Library
from datetime import date

# Third Party
import pytest

APP = "organizations"
# Migrations under test, found by name rather than by number.  Branches
# further up the stack add migrations of their own, and a number pinned here
# would go stale the first time one landed below it - the name is the part
# that does not move.
PARENT = "subscription_parent"
ITEM_CANCELLATION = "subscription_item_cancellation"


def _bracket(suffix):
    """Return the named migration and the one immediately before it."""
    loader = MigrationLoader(connection)
    target = next(
        name
        for app, name in loader.graph.nodes
        if app == APP and name.endswith(suffix)
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
        old = migrate_to(_bracket(PARENT)[0])
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

        new = migrate_to(_bracket(PARENT)[1])

        Subscription = new.get_model(APP, "Subscription")
        subscriptions = Subscription.objects.filter(organization=organization.pk)
        assert subscriptions.count() == 1
        assert subscriptions.first().items.count() == 2
        assert subscriptions.first().subscription_id == "sub_shared"

    def test_a_different_shape_gets_its_own_parent(self):
        """Stripe cannot bill monthly and annual on one subscription."""
        old = migrate_to(_bracket(PARENT)[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Mixed")
        SubscriptionItem.objects.create(
            organization=organization, plan=self._plan(old, "Monthly")
        )
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "Yearly", annual=True),
        )

        new = migrate_to(_bracket(PARENT)[1])

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
        old = migrate_to(_bracket(PARENT)[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Doubled")
        for plan_name, stripe_id in (("A", "sub_a"), ("B", "sub_b")):
            SubscriptionItem.objects.create(
                organization=organization,
                plan=self._plan(old, plan_name),
                subscription_id=stripe_id,
            )

        with pytest.raises(Exception, match="more than one"):
            migrate_to(_bracket(PARENT)[1])

    def test_lines_that_disagree_about_cancelling_are_refused(self):
        """A parent holds one answer, and both ways of guessing cost money.

        Collapsing with `all` renews a plan the customer cancelled;
        collapsing with `any` cancels ones they kept.  Until per-line
        cancellation exists there is nowhere to record the difference, so
        this refuses rather than picks.
        """
        old = migrate_to(_bracket(PARENT)[0])
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

        with pytest.raises(Exception, match="disagree about cancelling"):
            migrate_to(_bracket(PARENT)[1])

    def test_a_group_that_agrees_carries_its_answer_up(self):
        """The shape every group has today: lines that say the same thing."""
        old = migrate_to(_bracket(PARENT)[0])
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = self._organization(old, "Leaving")
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "First"),
            subscription_id="sub_leaving",
            cancelled=True,
            cancel_at=date(2026, 11, 1),
        )
        SubscriptionItem.objects.create(
            organization=organization,
            plan=self._plan(old, "Second"),
            cancelled=True,
            cancel_at=date(2026, 11, 1),
        )

        new = migrate_to(_bracket(PARENT)[1])

        Subscription = new.get_model(APP, "Subscription")
        subscription = Subscription.objects.get(organization=organization.pk)
        assert subscription.cancelled
        assert subscription.cancel_at == date(2026, 11, 1)


@pytest.mark.django_db(transaction=True)
class TestRollingTheSplitBack:
    """Reversing with rows in the table, which is the only case that matters.

    A migration that only reverses on an empty database is not reversible;
    it just has not been asked.  This release is the one carrying the data
    move, so its rollback is worth more than the others'.
    """

    @pytest.fixture(autouse=True)
    def _leave_the_database_migrated(self):
        yield
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM organizations_subscriptionitem")
        migrate_to_latest()

    def test_the_lines_survive_a_rollback(self):
        before, target = _bracket(PARENT)
        old = migrate_to(before)
        Organization = old.get_model(APP, "Organization")
        Plan = old.get_model(APP, "Plan")
        SubscriptionItem = old.get_model(APP, "SubscriptionItem")
        organization = Organization.objects.create(name="Rollback", slug="rollback")
        SubscriptionItem.objects.create(
            organization=organization,
            plan=Plan.objects.create(name="Rollback Plan", slug="rollback-plan"),
            subscription_id="sub_rollback",
            stripe_status="active",
        )
        migrate_to(target)

        back = migrate_to(before)

        SubscriptionItem = back.get_model(APP, "SubscriptionItem")
        line = SubscriptionItem.objects.get()
        assert line.organization_id == organization.pk
        assert line.subscription_id == "sub_rollback"
        assert line.stripe_status == "active"


@pytest.mark.django_db(transaction=True)
class TestAdoptParentCancellation:
    """A pending cancellation has to survive the columns moving twice.

    `subscription_parent` moves the pair onto the parent and drops the
    line's columns; this migration adds them back for per-line cancellation
    and would otherwise leave every line saying it renews.
    """

    @pytest.fixture(autouse=True)
    def _leave_the_database_migrated(self):
        yield
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM organizations_subscriptionitem")
            cursor.execute("DELETE FROM organizations_subscription")
        migrate_to_latest()

    def _subscription(self, apps, *, cancelled, cancel_at=None):
        Organization = apps.get_model(APP, "Organization")
        Plan = apps.get_model(APP, "Plan")
        Subscription = apps.get_model(APP, "Subscription")
        SubscriptionItem = apps.get_model(APP, "SubscriptionItem")

        name = f"Org {cancelled}-{cancel_at}"
        subscription = Subscription.objects.create(
            organization=Organization.objects.create(name=name, slug=slugify(name)),
            cancelled=cancelled,
            cancel_at=cancel_at,
        )
        SubscriptionItem.objects.create(
            subscription=subscription,
            plan=Plan.objects.create(name=f"Plan {name}", slug=slugify(f"p {name}")),
        )
        return subscription

    def test_a_cancelled_parent_hands_its_lines_the_cancellation(self):
        """Otherwise the billing page tells the customer they renew."""
        before, target = _bracket(ITEM_CANCELLATION)
        old = migrate_to(before)
        ending = date(2026, 10, 20)
        subscription = self._subscription(old, cancelled=True, cancel_at=ending)

        new = migrate_to(target)

        SubscriptionItem = new.get_model(APP, "SubscriptionItem")
        line = SubscriptionItem.objects.get(subscription_id=subscription.pk)
        assert line.cancelled
        assert line.cancel_at == ending

    def test_a_live_parent_leaves_its_lines_renewing(self):
        before, target = _bracket(ITEM_CANCELLATION)
        old = migrate_to(before)
        subscription = self._subscription(old, cancelled=False)

        new = migrate_to(target)

        SubscriptionItem = new.get_model(APP, "SubscriptionItem")
        line = SubscriptionItem.objects.get(subscription_id=subscription.pk)
        assert not line.cancelled
        assert line.cancel_at is None
