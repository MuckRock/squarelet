# Django
from django.core.management import call_command
from django.core.management.base import CommandError

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.management.commands.backfill_plan_prices import (
    DEFERRED_SLUGS,
    LEGACY_PLAN_MAP,
)
from squarelet.organizations.models import Plan, Subscription
from squarelet.organizations.tests.factories import (
    OrganizationFactory,
    PlanFactory,
    PlanPriceFactory,
    SubscriptionFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.fixture(name="targets")
def targets_fixture(db):  # pylint: disable=unused-argument
    """Every PlanPrice the map points at.

    _preflight refuses to run unless all of them exist, so this builds the
    whole target set rather than just the ones a given test uses.  Derived
    from LEGACY_PLAN_MAP so it cannot drift from it.
    """
    plans = {}
    for slug, interval, label, code in set(LEGACY_PLAN_MAP.values()):
        if slug not in plans:
            plans[slug] = PlanFactory(name=f"Canonical {slug}", slug=slug)
        PlanPriceFactory(
            plan=plans[slug],
            interval=interval,
            label=label,
            code=code,
            amount=0 if label == "comped" else 10_000,
        )
    return plans


def legacy(slug, **kwargs):
    """A legacy plan under its real slug.

    Several legacy slugs are also canonical ones - `professional` maps to
    itself - so reuse the row the targets fixture already made rather than
    letting AutoSlugField uniquify a duplicate into `professional-2`.
    """
    existing = Plan.objects.filter(slug=slug).first()
    if existing is not None:
        for field, value in kwargs.items():
            setattr(existing, field, value)
        if kwargs:
            existing.save()
        return existing
    return PlanFactory(name=f"Legacy {slug}", slug=slug, **kwargs)


def run(**kwargs):
    out = StringIO()
    call_command("backfill_plan_prices", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db()
class TestBillingDecidesTheLabel:
    """is_billing is what separates a paying subscriber from a comped one."""

    def test_billing_subscription_gets_the_standard_price(self, targets):
        actor = UserFactory()
        sub = SubscriptionFactory(
            plan=legacy("professional"), subscription_id="sub_live"
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price.label == "standard"
        assert sub.plan == targets["professional"]

    @pytest.mark.usefixtures("targets")
    def test_non_billing_subscription_gets_the_comped_price(self):
        """Years of admin-granted free access live on plans that look paid."""
        actor = UserFactory()
        sub = SubscriptionFactory(plan=legacy("professional"), subscription_id=None)

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price.label == "comped"

    @pytest.mark.usefixtures("targets")
    def test_comped_migration_records_who_authorized_it(self):
        actor = UserFactory()
        sub = SubscriptionFactory(plan=legacy("beta"), subscription_id=None)

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.granted_by == actor
        assert "beta" in sub.granted_reason.lower()

    @pytest.mark.usefixtures("targets")
    def test_standard_migration_records_no_provenance(self):
        actor = UserFactory()
        sub = SubscriptionFactory(
            plan=legacy("professional"), subscription_id="sub_live"
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.granted_by is None
        assert sub.granted_reason == ""


@pytest.mark.django_db()
class TestWhatIsLeftAlone:
    @pytest.mark.usefixtures("targets")
    def test_deferred_slugs_are_not_touched(self):
        actor = UserFactory()
        slug = sorted(DEFERRED_SLUGS)[0]
        sub = SubscriptionFactory(plan=legacy(slug), subscription_id=None)

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price is None

    @pytest.mark.usefixtures("targets")
    def test_per_user_subscribers_still_billing_are_skipped(self):
        """They need decomposing, which changes what Stripe charges."""
        actor = UserFactory()
        sub = SubscriptionFactory(
            plan=legacy("organization", price_per_user=10),
            subscription_id="sub_live",
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price is None

    @pytest.mark.usefixtures("targets")
    def test_a_comped_per_user_subscriber_is_not_skipped(self):
        """The subtle one.

        The exclusion is per-user AND billing.  A comped organization is on a
        per-user plan with no Stripe subscription, and must still be migrated
        -- dropping it here would strand it with a null plan_price and fail
        step 3c much later.
        """
        actor = UserFactory()
        sub = SubscriptionFactory(
            plan=legacy("organization", price_per_user=10), subscription_id=None
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price is not None
        assert sub.plan_price.label == "comped"


@pytest.mark.django_db()
class TestPreflightRefusesToGuess:
    """The command has no log-and-skip path; it stops instead."""

    @pytest.mark.usefixtures("targets")
    def test_unmapped_plan_aborts(self):
        actor = UserFactory()
        SubscriptionFactory(plan=legacy("not-in-the-map"), subscription_id=None)

        with pytest.raises(CommandError, match="No mapping for"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_unmapped_plan_writes_nothing(self):
        actor = UserFactory()
        good = SubscriptionFactory(
            plan=legacy("professional"), subscription_id="sub_live"
        )
        SubscriptionFactory(plan=legacy("not-in-the-map"), subscription_id=None)

        with pytest.raises(CommandError):
            run(actor=actor.username)

        good.refresh_from_db()
        assert good.plan_price is None

    @pytest.mark.usefixtures("db")
    def test_missing_target_price_aborts(self):
        actor = UserFactory()
        SubscriptionFactory(plan=legacy("professional"), subscription_id="sub_live")

        with pytest.raises(CommandError, match="consolidate_stripe_products"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_collapsing_two_plans_onto_one_aborts(self):
        """Two legacy comps for one org would trip unique_together mid-loop."""
        actor = UserFactory()
        org = OrganizationFactory()
        SubscriptionFactory(
            organization=org, plan=legacy("premium-org-comp"), subscription_id=None
        )
        SubscriptionFactory(
            organization=org, plan=legacy("education-grant"), subscription_id=None
        )

        with pytest.raises(CommandError, match="collapse onto one plan"):
            run(actor=actor.username)

    def test_actor_is_required_unless_dry_running(self):
        with pytest.raises(CommandError, match="--actor is required"):
            run()

    def test_unknown_actor_aborts(self):
        with pytest.raises(CommandError, match="No such user"):
            run(actor="nobody")


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestDryRun:
    def test_dry_run_writes_nothing(self):
        sub = SubscriptionFactory(
            plan=legacy("professional"), subscription_id="sub_live"
        )

        output = run(dry_run=True)

        sub.refresh_from_db()
        assert sub.plan_price is None
        assert "DRY RUN" in output

    def test_dry_run_needs_no_actor(self):
        SubscriptionFactory(plan=legacy("professional"), subscription_id=None)

        run(dry_run=True)

        assert Subscription.objects.filter(plan_price__isnull=False).count() == 0


@pytest.mark.django_db()
class TestCollisionWithARowItLeavesAlone:
    """A collision does not have to be between two pending rows.

    A per-user subscriber still billing is excluded from this step, but it
    still occupies (organization, plan).  A legacy comp for the same
    organization that maps onto that same canonical plan collides with it,
    and must be reported up front rather than aborting the write half way
    through with a bare IntegrityError.
    """

    @pytest.mark.usefixtures("targets")
    def test_collision_with_an_excluded_subscription_is_reported(self):
        actor = UserFactory()
        org = OrganizationFactory()
        SubscriptionFactory(
            organization=org,
            plan=legacy("organization", price_per_user=10),
            subscription_id="sub_live",
        )
        SubscriptionFactory(
            organization=org,
            plan=legacy("premium-org-comp"),
            subscription_id=None,
        )

        with pytest.raises(CommandError, match="collapse onto one plan"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_an_unrelated_existing_subscription_is_not_a_collision(self):
        """Different organization, same canonical plan - no conflict."""
        actor = UserFactory()
        SubscriptionFactory(
            plan=legacy("organization", price_per_user=10),
            subscription_id="sub_live",
        )
        migrating = SubscriptionFactory(
            plan=legacy("premium-org-comp"), subscription_id=None
        )

        run(actor=actor.username)

        migrating.refresh_from_db()
        assert migrating.plan_price is not None
