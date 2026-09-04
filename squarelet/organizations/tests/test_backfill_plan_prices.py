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
    PACK_DECOMPOSITION,
    PACK_SLUGS,
)
from squarelet.organizations.management.commands.consolidate_stripe_products import (
    PRICE_MATRIX,
)
from squarelet.organizations.models import Plan, SubscriptionItem
from squarelet.organizations.tests.factories import (
    OrganizationFactory,
    PlanFactory,
    PlanPriceFactory,
    SubscriptionItemFactory,
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
            # Reuse the migration-seeded plan when it is there.  Whether it
            # is depends on whether a transactional test has flushed the
            # database yet, and creating a second one would quietly become
            # `professional-2` via AutoSlugField - which the command then
            # cannot find, making these tests pass or fail on run order.
            plans[slug] = Plan.objects.filter(slug=slug).first() or PlanFactory(
                name=f"Canonical {slug}", slug=slug
            )
        PlanPriceFactory(
            plan=plans[slug],
            interval=interval,
            label=label,
            code=code,
            amount=0 if label == "comped" else 10_000,
        )

    # Packs, at a tenth of a tier.  A legacy plan in these tests bills
    # $100 + $10 a block, so a decomposed subscriber comes to exactly the
    # same money and the command's bill check passes.
    for pack_slug in sorted(PACK_SLUGS):
        plans[pack_slug] = Plan.objects.filter(slug=pack_slug).first() or PlanFactory(
            name=f"Pack {pack_slug}", slug=pack_slug
        )
        for interval in ("monthly", "annual"):
            PlanPriceFactory(
                plan=plans[pack_slug],
                interval=interval,
                label="standard",
                code="",
                amount=1_000,
            )
    return plans


@pytest.fixture(name="stripe", autouse=True)
def stripe_fixture(mocker):
    """An inert Stripe, so the run reaches `modify` without leaving here."""
    mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
    service = mocker.patch(
        "squarelet.organizations.models.payment.get_payment_provider"
    ).return_value.get_subscription_service.return_value
    service.modify.return_value = None
    return service


def legacy(slug, **kwargs):
    """A legacy plan under its real slug.

    Several legacy slugs are also canonical ones - `professional` maps to
    itself - so reuse the row the targets fixture already made rather than
    letting AutoSlugField uniquify a duplicate into `professional-2`.
    """
    # $100 flat by default, matching the $100 tier price the targets
    # fixture creates.  The command refuses to migrate anyone whose bill
    # would change, so a legacy plan billing nothing against a tier billing
    # $100 is not a usable default.
    kwargs.setdefault("base_price", 100)
    existing = Plan.objects.filter(slug=slug).first()
    if existing is not None:
        for field, value in kwargs.items():
            setattr(existing, field, value)
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
        sub = SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id="sub_live"
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price.label == "standard"
        assert sub.plan == targets["professional"]

    @pytest.mark.usefixtures("targets")
    def test_non_billing_subscription_gets_the_comped_price(self):
        """Years of admin-granted free access live on plans that look paid."""
        actor = UserFactory()
        sub = SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id=""
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price.label == "comped"

    @pytest.mark.usefixtures("targets")
    def test_comped_migration_records_who_authorized_it(self):
        actor = UserFactory()
        sub = SubscriptionItemFactory(
            plan=legacy("beta"), subscription__subscription_id=""
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.granted_by == actor
        assert "beta" in sub.granted_reason.lower()

    @pytest.mark.usefixtures("targets")
    def test_standard_migration_records_no_provenance(self):
        actor = UserFactory()
        sub = SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id="sub_live"
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
        sub = SubscriptionItemFactory(
            plan=legacy(slug), subscription__subscription_id=""
        )

        run(actor=actor.username)

        sub.refresh_from_db()
        assert sub.plan_price is None

    @pytest.mark.usefixtures("targets")
    def test_pack_lines_from_an_earlier_run_are_not_reprocessed(self):
        """A pack is an output of this command, never an input.

        Feeding one back in would look for `muckrock-request-pack` in the
        legacy map and abort the whole run on an unmapped slug.
        """
        actor = UserFactory()
        pack_slug = sorted(PACK_SLUGS)[0]
        item = SubscriptionItemFactory(
            plan=legacy(pack_slug), subscription__subscription_id="sub_live"
        )

        run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price is None

    @pytest.mark.usefixtures("targets")
    def test_a_comped_per_user_subscriber_is_not_skipped(self):
        """The subtle one.

        The exclusion is per-user AND billing.  A comped organization is on a
        per-user plan with no Stripe subscription, and must still be migrated
        -- dropping it here would strand it with a null plan_price and fail
        step 3c much later.
        """
        actor = UserFactory()
        sub = SubscriptionItemFactory(
            plan=legacy("organization", price_per_user=10),
            subscription__subscription_id="",
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
        SubscriptionItemFactory(
            plan=legacy("not-in-the-map"), subscription__subscription_id=""
        )

        with pytest.raises(CommandError, match="No mapping for"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_unmapped_plan_writes_nothing(self):
        actor = UserFactory()
        good = SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id="sub_live"
        )
        SubscriptionItemFactory(
            plan=legacy("not-in-the-map"), subscription__subscription_id=""
        )

        with pytest.raises(CommandError):
            run(actor=actor.username)

        good.refresh_from_db()
        assert good.plan_price is None

    @pytest.mark.usefixtures("db")
    def test_missing_target_price_aborts(self):
        actor = UserFactory()
        SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id="sub_live"
        )

        with pytest.raises(CommandError, match="consolidate_stripe_products"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_collapsing_two_plans_onto_one_aborts(self):
        """Two legacy comps for one org would trip unique_together mid-loop."""
        actor = UserFactory()
        org = OrganizationFactory()
        SubscriptionItemFactory(
            subscription__organization=org,
            plan=legacy("premium-org-comp"),
            subscription__subscription_id="",
        )
        SubscriptionItemFactory(
            subscription__organization=org,
            plan=legacy("education-grant"),
            subscription__subscription_id="",
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
        sub = SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id="sub_live"
        )

        output = run(dry_run=True)

        sub.refresh_from_db()
        assert sub.plan_price is None
        assert "DRY RUN" in output

    def test_dry_run_needs_no_actor(self):
        SubscriptionItemFactory(
            plan=legacy("professional"), subscription__subscription_id=""
        )

        run(dry_run=True)

        assert SubscriptionItem.objects.filter(plan_price__isnull=False).count() == 0


@pytest.mark.django_db()
class TestCollisionWithALineItLeavesAlone:
    """A collision does not have to be between two pending lines.

    A per-user line still billing is excluded from this step, but it still
    occupies (subscription, plan).  Another line on the same subscription
    that maps onto that same canonical plan collides with it, and must be
    reported up front rather than aborting the write half way through with
    a bare IntegrityError.
    """

    @pytest.mark.usefixtures("targets")
    def test_collision_with_an_excluded_line_is_reported(self):
        actor = UserFactory()
        # Excluded: per-user and billing
        excluded = SubscriptionItemFactory(
            plan=legacy("professional", price_per_user=5),
            subscription__subscription_id="sub_live",
        )
        # Pending, and `beta` maps onto canonical `professional`
        SubscriptionItemFactory(subscription=excluded.subscription, plan=legacy("beta"))

        with pytest.raises(CommandError, match="collapse onto one plan"):
            run(actor=actor.username)

    @pytest.mark.usefixtures("targets")
    def test_lines_on_different_subscriptions_do_not_collide(self):
        """Uniqueness is per subscription, so separate parents are fine."""
        actor = UserFactory()
        org = OrganizationFactory()
        SubscriptionItemFactory(
            subscription__organization=org,
            plan=legacy("professional", price_per_user=5),
            subscription__subscription_id="sub_live",
        )
        migrating = SubscriptionItemFactory(
            subscription__organization=org,
            subscription__interval="annual",
            plan=legacy("beta"),
        )

        run(actor=actor.username)

        migrating.refresh_from_db()
        assert migrating.plan_price is not None


def per_user(slug="organization", quantity=30, **kwargs):
    """A subscriber holding resource blocks over their plan's minimum."""
    return SubscriptionItemFactory(
        plan=legacy(slug, base_price=100, minimum_users=5, price_per_user=10),
        subscription__subscription_id="sub_live",
        quantity=quantity,
        **kwargs,
    )


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestDecomposition:
    """Per-user subscribers become a flat tier line plus usage packs."""

    def test_the_base_line_drops_to_quantity_one(self):
        """Easy to miss and expensive to miss.

        The line carries the block count today.  Billing a flat Price at
        quantity 30 charges thirty times the tier.
        """
        actor = UserFactory()
        item = per_user(quantity=30)

        run(actor=actor.username)

        item.refresh_from_db()
        assert item.quantity == 1
        assert item.plan_price.plan.slug == "organization"

    def test_a_pack_line_carries_the_blocks(self):
        actor = UserFactory()
        item = per_user(quantity=30)

        run(actor=actor.username)

        pack = SubscriptionItem.objects.get(
            subscription=item.subscription, plan__slug="muckrock-request-pack"
        )
        # 30 held, 5 included in the tier.
        assert pack.quantity == 25
        assert pack.plan_price.amount == 1_000

    def test_the_two_lines_total_the_old_bill(self):
        actor = UserFactory()
        item = per_user(quantity=30)

        run(actor=actor.username)

        item.refresh_from_db()
        lines = SubscriptionItem.objects.filter(subscription=item.subscription)
        total = sum(line.plan_price.amount * line.quantity for line in lines)
        # $100 + 25 blocks x $10 = $350, before and after.
        assert total == 35_000

    def test_both_lines_sit_on_one_subscription(self):
        """A single invoice is the point of the Subscription/item split."""
        actor = UserFactory()
        item = per_user()

        run(actor=actor.username)

        assert (
            SubscriptionItem.objects.filter(subscription=item.subscription).count() == 2
        )

    def test_a_subscriber_at_the_minimum_gets_no_pack(self):
        actor = UserFactory()
        item = per_user(quantity=5)

        run(actor=actor.username)

        item.refresh_from_db()
        assert item.quantity == 5
        assert not SubscriptionItem.objects.filter(
            subscription=item.subscription, plan__slug__in=PACK_SLUGS
        ).exists()

    def test_a_comped_per_user_line_is_repointed_but_not_decomposed(self):
        """Nothing is billing, so there is no overage to reproduce."""
        actor = UserFactory()
        item = SubscriptionItemFactory(
            plan=legacy("organization", minimum_users=5, price_per_user=10),
            subscription__subscription_id="",
            quantity=30,
        )

        run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price.label == "comped"
        assert item.quantity == 30
        assert not SubscriptionItem.objects.filter(
            subscription=item.subscription, plan__slug__in=PACK_SLUGS
        ).exists()

    def test_only_the_plans_with_real_block_holders_are_listed(self):
        """Twelve organizations hold blocks and all are on an Org plan.

        Nobody can join them - the purchase flow hardcodes `minimum_users`,
        so self-service cannot sell a block.  Listing the Sunlight tiers
        too would be a guess nothing exercises, and the preflight refuses
        to run if one ever does turn up.
        """
        assert set(PACK_DECOMPOSITION) == {"organization", "organization-annual"}

    def test_an_unlisted_plan_with_block_holders_aborts(self):
        actor = UserFactory()
        SubscriptionItemFactory(
            plan=legacy("professional", minimum_users=5, price_per_user=10),
            subscription__subscription_id="sub_live",
            quantity=30,
        )

        with pytest.raises(CommandError, match="PACK_DECOMPOSITION"):
            run(actor=actor.username)


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestTheBillMustNotChange:
    """proration_behavior="none" hides a mismatch; it does not fix one.

    Suppressing proration stops the mid-cycle adjustment, but the next
    invoice bills the new Price whatever it says.  So the bill is preserved
    only if the amounts genuinely agree, which is checked rather than
    assumed.
    """

    def test_a_mismatched_tier_price_is_refused(self):
        actor = UserFactory()
        # $250 today against the $100 tier the fixture created.
        item = SubscriptionItemFactory(
            plan=legacy("professional", base_price=250),
            subscription__subscription_id="sub_live",
        )

        with pytest.raises(CommandError):
            run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price is None

    def test_a_mismatched_pack_rate_is_refused(self):
        """The nonprofit and legacy-Basic hazard, checked by arithmetic.

        Both charge less per block than a standard pack.  Rather than name
        them, the command refuses anyone the sum does not reproduce.
        """
        actor = UserFactory()
        item = per_user(quantity=30)
        item.plan.price_per_user = 5  # half the pack rate
        item.plan.save()

        with pytest.raises(CommandError):
            run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price is None
        assert item.quantity == 30

    def test_one_refusal_does_not_stop_the_others(self):
        """Stripe cannot be rolled back, so the run is per subscription."""
        actor = UserFactory()
        bad = SubscriptionItemFactory(
            plan=legacy("professional", base_price=250),
            subscription__subscription_id="sub_bad",
        )
        good = SubscriptionItemFactory(
            plan=legacy("organization", base_price=100, minimum_users=5),
            subscription__subscription_id="sub_good",
        )

        with pytest.raises(CommandError):
            run(actor=actor.username)

        bad.refresh_from_db()
        good.refresh_from_db()
        assert bad.plan_price is None
        assert good.plan_price is not None


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestStripeSwitchover:
    def test_stripe_is_told_not_to_prorate(self, stripe):
        actor = UserFactory()
        per_user(quantity=30)

        run(actor=actor.username)

        assert stripe.modify.call_args.kwargs["proration_behavior"] == "none"

    def test_the_pack_reaches_stripe_in_the_same_call(self, stripe):
        """One call, so nobody is ever billed a half-migrated subscription."""
        actor = UserFactory()
        per_user(quantity=30)

        run(actor=actor.username)

        assert stripe.modify.call_count == 1
        quantities = sorted(
            line["quantity"] for line in stripe.modify.call_args.kwargs["items"]
        )
        assert quantities == [1, 25]

    def test_local_only_leaves_stripe_alone(self, stripe):
        actor = UserFactory()
        item = per_user()

        run(actor=actor.username, local_only=True)

        item.refresh_from_db()
        assert item.plan_price is not None
        stripe.modify.assert_not_called()

    def test_a_stripe_failure_rolls_back_that_subscription(self, stripe):
        """No local trace of a change Stripe refused to make."""
        actor = UserFactory()
        stripe.modify.side_effect = ValueError("stripe said no")
        item = per_user(quantity=30)

        with pytest.raises(CommandError):
            run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price is None
        assert item.quantity == 30
        assert not SubscriptionItem.objects.filter(
            subscription=item.subscription, plan__slug__in=PACK_SLUGS
        ).exists()


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestRerunning:
    """Safe to run twice, with no "done" marker to get out of step.

    Selecting on `plan_price__isnull=True` would have been the obvious way
    to make this cheap, and would have stranded exactly the rows that most
    need a second attempt: the ones whose local half committed and whose
    Stripe half did not.
    """

    def test_a_second_run_changes_nothing(self):
        actor = UserFactory()
        item = per_user(quantity=30)

        run(actor=actor.username)
        first = {
            (line.plan.slug, line.quantity, line.plan_price_id)
            for line in SubscriptionItem.objects.filter(subscription=item.subscription)
        }
        run(actor=actor.username)
        second = {
            (line.plan.slug, line.quantity, line.plan_price_id)
            for line in SubscriptionItem.objects.filter(subscription=item.subscription)
        }

        assert first == second

    def test_a_second_run_does_not_duplicate_the_pack(self):
        actor = UserFactory()
        item = per_user(quantity=30)

        run(actor=actor.username)
        run(actor=actor.username)

        assert (
            SubscriptionItem.objects.filter(
                subscription=item.subscription, plan__slug="muckrock-request-pack"
            ).count()
            == 1
        )

    def test_a_line_whose_stripe_half_failed_is_picked_up(self, stripe):
        actor = UserFactory()
        stripe.modify.side_effect = ValueError("stripe said no")
        item = per_user(quantity=30)
        with pytest.raises(CommandError):
            run(actor=actor.username)

        stripe.modify.side_effect = None
        run(actor=actor.username)

        item.refresh_from_db()
        assert item.plan_price is not None
        assert item.quantity == 1


# The twelve organizations holding blocks over their minimum in production,
# as of Sep 2026.  Nobody can join them: the purchase flow hardcodes
# `minimum_users`, so self-service cannot sell a block.
PROD_BLOCK_HOLDERS = [
    ("organization", 7),  # FinePrint Media
    ("organization", 6),  # FIRE
    ("organization", 10),  # Armada Analytics
    ("organization", 11),  # Undark
    ("organization", 6),  # Everytown For Gun Safety
    ("organization", 15),  # Electronic Frontier Foundation
    ("organization", 15),  # Wired.com
    ("organization", 7),  # The Examination
    ("organization", 8),  # The Trace
    ("organization", 18),  # Transparency Project
    ("organization-annual", 10),  # BitSight
    ("organization-annual", 7),  # Nieman Foundation
]

# What the legacy plans charge, from the plan inventory.
LEGACY_RATES = {
    "organization": {"base_price": 100, "minimum_users": 5, "price_per_user": 10},
    "organization-annual": {
        "base_price": 1_200,
        "minimum_users": 5,
        "price_per_user": 120,
    },
}


class TestTheRealSubscribersReconcile:
    """Every production block-holder comes out at the same money.

    The command refuses a subscriber whose bill would change, so this is
    what stands between the price matrix and a run that migrates nobody.
    Cheaper to find here than in a dry run against production.
    """

    @pytest.mark.parametrize(("slug", "quantity"), PROD_BLOCK_HOLDERS)
    def test_bill_is_unchanged(self, slug, quantity):
        rates = LEGACY_RATES[slug]
        interval = "annual" if slug.endswith("-annual") else "monthly"
        amounts = {
            (plan_slug, plan_interval): cents
            for plan_slug, plan_interval, label, code, cents in PRICE_MATRIX
            if label == "standard" and code == ""
        }

        blocks = quantity - rates["minimum_users"]
        old = 100 * (rates["base_price"] + blocks * rates["price_per_user"])
        new = amounts[("organization", interval)] + blocks * sum(
            amounts[(pack, interval)] for pack in PACK_DECOMPOSITION[slug]
        )

        assert new == old, (
            f"{slug} at {quantity} blocks bills ${old / 100:,.2f} today and "
            f"${new / 100:,.2f} after"
        )
