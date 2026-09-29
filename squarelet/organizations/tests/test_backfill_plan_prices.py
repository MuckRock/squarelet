# The command's steps are the unit under test here.
# pylint: disable=protected-access
# Django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.management.commands.backfill_plan_prices import (
    PACK_SLUGS,
    Command,
)
from squarelet.organizations.models import (
    Plan,
    PlanPrice,
    Subscription,
    SubscriptionItem,
)
from squarelet.organizations.plan_mapping import LEGACY_PLAN_MAP
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    InvoiceFactory,
    OrganizationFactory,
    PlanFactory,
    PlanPriceFactory,
    SubscriptionItemFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.fixture(name="targets")
def targets_fixture(db):  # pylint: disable=unused-argument
    """Every price the map points at: $100 standard, $0 comped."""
    plans = {}
    for slug, interval, label, code in set(LEGACY_PLAN_MAP.values()):
        if slug not in plans:
            # Reuse a migration-seeded plan, or AutoSlugField makes `<slug>-2`.
            plans[slug] = Plan.objects.filter(slug=slug).first() or PlanFactory(
                name=f"Canonical {slug}", slug=slug
            )
            # A seeded plan's real entitlements would reach the grant check.
            plans[slug].entitlements.clear()
        PlanPriceFactory(
            plan=plans[slug],
            interval=interval,
            label=label,
            code=code,
            amount=0 if label == "comped" else 10_000,
        )
    # Packs at a tenth of a tier, so $100 + $10 a block comes out even.
    for pack_slug in sorted(PACK_SLUGS):
        plans[pack_slug] = Plan.objects.filter(slug=pack_slug).first() or PlanFactory(
            name=f"Pack {pack_slug}", slug=pack_slug
        )
        plans[pack_slug].entitlements.clear()
        for interval in ("monthly", "annual"):
            for label, amount in (("standard", 1_000), ("comped", 0)):
                PlanPriceFactory(
                    plan=plans[pack_slug],
                    interval=interval,
                    label=label,
                    amount=amount,
                )
    return plans


def legacy(slug, **kwargs):
    """A legacy plan under its real slug, billing $100 flat by default."""
    kwargs.setdefault("base_price", 100)
    kwargs.setdefault("for_groups", False)
    existing = Plan.objects.filter(slug=slug).first()
    if existing is not None:
        for field, value in kwargs.items():
            setattr(existing, field, value)
        existing.save()
        existing.entitlements.clear()
        return existing
    return PlanFactory(name=f"Legacy {slug}", slug=slug, **kwargs)


def line(slug="professional", billing=True, **kwargs):
    return SubscriptionItemFactory(
        plan=legacy(slug, **kwargs.pop("plan_fields", {})),
        subscription__subscription_id="sub_live" if billing else "",
        **kwargs,
    )


def run(**kwargs):
    out = StringIO()
    call_command("backfill_plan_prices", stdout=out, **kwargs)
    return out.getvalue()


@pytest.fixture(name="actor")
def actor_fixture(db):  # pylint: disable=unused-argument
    return UserFactory().username


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestBillingDecidesTheLabel:
    def test_a_billing_line_gets_the_standard_price(self, targets, actor):
        item = line("professional")

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price.label == "standard"
        assert item.plan == targets["professional"]
        assert item.granted_by is None

    def test_a_line_nothing_bills_gets_the_comped_price(self, actor):
        """Admins comped by putting organizations on paid plans."""
        item = line("professional", billing=False)

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price.label == "comped"
        assert item.granted_by.username == actor
        assert "professional" in item.granted_reason.lower()


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestACompedLineIsFree:
    """A $0 price belongs on the organization's free subscription."""

    def test_its_own_row_becomes_the_free_one(self, actor):
        item = line("beta", billing=False)

        run(actor=actor)

        item.refresh_from_db()
        assert item.subscription.kind == "free"

    def test_it_joins_an_existing_free_row(self, actor):
        item = line("beta", billing=False)
        organization = item.subscription.organization
        free = Subscription.objects.create(organization=organization, kind="free")
        left = item.subscription
        invoice = InvoiceFactory(organization=organization, subscription=left)

        run(actor=actor)

        item.refresh_from_db()
        invoice.refresh_from_db()
        assert item.subscription == free
        assert not Subscription.objects.filter(pk=left.pk).exists()
        assert invoice.subscription == free

    def test_every_comped_line_ends_on_one_free_row(self, actor):
        first = line("beta", billing=False)
        second = SubscriptionItemFactory(
            subscription=first.subscription, plan=legacy("education-grant")
        )
        left = first.subscription

        run(actor=actor)

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.subscription == second.subscription
        assert first.subscription.kind == "free"
        assert not Subscription.objects.filter(pk=left.pk, kind="renewing").exists()


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestTheBillMustNotChange:
    def test_a_group_plan_bills_one_unit_of_its_price(self, actor):
        """Its base did not multiply; a flat Price does."""
        item = line(
            "organization",
            quantity=5,
            plan_fields={"for_groups": True, "minimum_users": 5, "price_per_user": 10},
        )

        run(actor=actor)

        item.refresh_from_db()
        assert item.quantity == 1
        assert item.plan_price.amount == 10_000

    def test_a_different_amount_is_refused(self, actor):
        item = line("professional", plan_fields={"base_price": 120})

        with pytest.raises(CommandError, match="failed"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None


@pytest.mark.django_db()
class TestTheCohortBillsAtTwoCadences:
    """The map says annual; each line's own subscription says how it bills."""

    @pytest.fixture(autouse=True)
    def _prices(self, targets):
        essential = targets["sunlight-essential"]
        for interval, amount in (("annual", 120_000), ("monthly", 10_000)):
            PlanPrice.objects.update_or_create(
                plan=essential,
                interval=interval,
                label="standard",
                code="election-cohort",
                defaults={"amount": amount, "stripe_price_id": f"price_{interval}"},
            )

    def _line(self, interval):
        return SubscriptionItemFactory(
            plan=legacy("election-accountability-cohort", base_price=1200, annual=True),
            subscription__subscription_id=f"sub_{interval}",
            subscription__interval=interval,
        )

    def test_only_the_cadences_in_use_must_exist(self, actor):
        PlanPrice.objects.filter(code="election-cohort", interval="annual").delete()
        item = self._line("monthly")

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price.interval == "monthly"

    def test_each_cohort_line_s_cadence_is_reported(self, actor):
        """The money check cannot tell $250 a month from $3,000 a year."""
        item = self._line("monthly")

        out = run(actor=actor)

        slug = item.subscription.organization.slug
        assert f"cohort {slug}: monthly" in out

    def test_a_monthly_line_takes_the_monthly_price(self, actor):
        item = self._line("monthly")

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price.interval == "monthly"

    def test_an_annual_line_takes_the_annual_price(self, actor):
        item = self._line("annual")

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price.interval == "annual"


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestPreflightRefusesToGuess:
    """Nothing is written unless every line is accounted for."""

    def test_an_unmapped_plan_stops_everything(self, actor):
        good = line("professional")
        line("not-in-the-map", billing=False)

        with pytest.raises(CommandError, match="No mapping for"):
            run(actor=actor)

        good.refresh_from_db()
        assert good.plan_price is None

    def test_a_billing_line_mapped_to_comped_is_refused(self, actor):
        """Stripe would go on charging it."""
        line("beta", billing=True)

        with pytest.raises(CommandError, match="map to a comped price"):
            run(actor=actor)

    def test_a_comped_line_on_an_ending_subscription_is_refused(self, actor):
        item = line("beta", billing=False)
        item.subscription.cancelled = True
        item.subscription.save()

        with pytest.raises(CommandError, match="subscriptions that are ending"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None

    def test_blocks_on_a_plan_with_no_pack_are_refused(self, actor):
        line(
            "professional",
            quantity=30,
            plan_fields={"for_groups": True, "minimum_users": 5, "price_per_user": 10},
        )

        with pytest.raises(CommandError, match="PACK_DECOMPOSITION"):
            run(actor=actor)

    def test_a_missing_target_price_is_refused(self, actor):
        PlanPrice.objects.filter(plan__slug="professional", label="standard").delete()
        line("professional")

        with pytest.raises(CommandError, match="consolidate_stripe_products"):
            run(actor=actor)

    def test_a_target_nobody_needs_may_be_missing(self, actor):
        PlanPrice.objects.filter(plan__slug="documentcloud-premium").delete()
        item = line("professional")

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is not None

    def test_two_lines_landing_on_one_plan_are_refused(self, actor):
        organization = OrganizationFactory()
        first = line("premium-org-comp", billing=False)
        first.subscription.organization = organization
        first.subscription.save()
        SubscriptionItemFactory(
            subscription=first.subscription, plan=legacy("education-grant")
        )

        with pytest.raises(CommandError, match="collapse onto one plan"):
            run(actor=actor)

    def test_a_line_already_held_counts_as_a_collision(self, actor, targets):
        item = line("custom-crp")
        SubscriptionItemFactory(
            subscription=item.subscription,
            plan=targets["organization"],
            plan_price=PlanPrice.objects.get(
                plan=targets["organization"],
                interval="monthly",
                label="standard",
                code="",
            ),
        )

        with pytest.raises(CommandError, match="already held"):
            run(actor=actor)

    def test_a_comped_line_collides_on_the_free_row(self, actor, targets):
        """It lands on the organization's free row, not the one it is on."""
        item = line("beta", billing=False)
        free = Subscription.objects.create(
            organization=item.subscription.organization, kind="free"
        )
        SubscriptionItemFactory(
            subscription=free,
            plan=targets["professional"],
            plan_price=PlanPrice.objects.get(
                plan=targets["professional"], interval="monthly", label="comped"
            ),
        )

        with pytest.raises(CommandError, match="already held"):
            run(actor=actor)

    def test_where_a_line_lands_is_decided_one_way(self, actor, targets):
        """By its price's kind, for the collision check and the write alike."""
        comped = PlanPrice.objects.get(
            plan=targets["professional"], interval="monthly", label="comped"
        )
        comped.amount = 500  # mis-seeded: comped, yet it costs something
        comped.save()
        item = line("beta", billing=False)
        free = Subscription.objects.create(
            organization=item.subscription.organization, kind="free"
        )
        SubscriptionItemFactory(
            subscription=free, plan=targets["professional"], plan_price=comped
        )
        stays_on = item.subscription

        run(actor=actor)

        item.refresh_from_db()
        assert item.subscription == stays_on

    def test_the_actor_is_required(self):
        with pytest.raises(CommandError, match="--actor is required"):
            run()

    def test_an_unknown_actor_is_refused(self):
        with pytest.raises(CommandError, match="No such user"):
            run(actor="nobody")


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestRunningIt:
    def test_a_dry_run_writes_nothing_and_needs_no_actor(self):
        item = line("professional")

        out = run(dry_run=True)

        item.refresh_from_db()
        assert item.plan_price is None
        assert "DRY RUN" in out

    def test_the_organization_hears_its_entitlements_changed(
        self, actor, mocker, django_capture_on_commit_callbacks
    ):
        invalidate = mocker.patch(
            "squarelet.organizations.management.commands.backfill_plan_prices"
            ".send_cache_invalidations"
        )
        item = line("professional")

        with django_capture_on_commit_callbacks(execute=True):
            run(actor=actor)

        invalidate.assert_called_with(
            "organization", item.subscription.organization.uuid
        )

    def test_a_change_made_during_the_run_is_kept(self, actor, mocker):
        """The run reads every line up front; its write must not undo others'."""
        item = line("professional")
        real = Command._prices_for

        def meanwhile(line_):
            SubscriptionItem.objects.filter(pk=line_.pk).update(stripe_item_id="si_new")
            return real(line_)

        mocker.patch.object(Command, "_prices_for", staticmethod(meanwhile))

        run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is not None
        assert item.stripe_item_id == "si_new"

    def test_a_second_run_leaves_migrated_lines_alone(self, actor):
        item = line("professional")
        run(actor=actor)

        out = run(actor=actor)

        assert "0 migrated, 1 already done" in out
        item.refresh_from_db()
        assert item.plan_price.label == "standard"

    def test_a_re_run_costs_the_same_however_many_lines_are_done(self, actor):
        def rerun_queries():
            run(actor=actor)
            with CaptureQueriesContext(connection) as queries:
                run(actor=actor)
            return len(queries)

        line("beta", billing=False)
        one = rerun_queries()
        line("beta", billing=False)
        line("beta", billing=False)

        assert rerun_queries() == one

    def test_a_deferred_slug_is_skipped(self, actor, mocker):
        mocker.patch(
            "squarelet.organizations.management.commands"
            ".backfill_plan_prices.DEFERRED_SLUGS",
            {"awaiting-a-decision"},
        )
        item = line("awaiting-a-decision", billing=False)

        out = run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None
        assert "awaiting-a-decision deferred" in out


GROUP = {"for_groups": True, "minimum_users": 5, "price_per_user": 10}


def block_holder(slug="organization", quantity=30, billing=True):
    """A subscriber holding resource blocks over their plan's minimum."""
    return line(slug, billing=billing, quantity=quantity, plan_fields=dict(GROUP))


def entitle(plan, resources, client=None):
    entitlement = EntitlementFactory(
        resources=resources, **({"client": client} if client else {})
    )
    plan.entitlements.add(entitlement)
    return entitlement


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestBlocksBecomePacks:
    def test_the_tier_line_drops_to_one_and_a_pack_carries_the_blocks(self, actor):
        item = block_holder(quantity=30)

        run(actor=actor)

        item.refresh_from_db()
        pack = SubscriptionItem.objects.get(
            subscription=item.subscription, plan__slug="muckrock-request-pack"
        )
        assert item.quantity == 1
        assert pack.quantity == 25
        assert pack.plan_price.amount == 1_000

    def test_the_bill_is_the_same_on_one_invoice(self, actor):
        """$100 + 25 blocks x $10, before and after."""
        item = block_holder(quantity=30)

        run(actor=actor)

        lines = SubscriptionItem.objects.filter(subscription=item.subscription)
        assert sum(line.plan_price.amount * line.quantity for line in lines) == 35_000

    def test_a_pack_rate_that_changes_the_bill_is_refused(self, actor):
        item = block_holder(quantity=30)
        item.plan.price_per_user = 5
        item.plan.save()

        with pytest.raises(CommandError, match="failed"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None
        assert item.quantity == 30

    def test_a_comped_block_holder_gets_a_free_pack_on_the_free_row(self, actor):
        item = block_holder(quantity=30, billing=False)

        run(actor=actor)

        item.refresh_from_db()
        pack = SubscriptionItem.objects.get(plan__slug="muckrock-request-pack")
        assert pack.subscription == item.subscription
        assert item.subscription.kind == "free"
        assert pack.quantity == 25
        assert pack.plan_price.amount == 0

    def test_pack_lines_are_not_migrated_again(self, actor):
        item = block_holder(quantity=30)
        run(actor=actor)

        out = run(actor=actor)

        assert "0 migrated, 1 already done" in out
        item.refresh_from_db()
        pack = SubscriptionItem.objects.get(plan__slug="muckrock-request-pack")
        assert pack.quantity == 25

    def test_a_pack_already_held_is_not_overwritten(self, actor, targets):
        item = block_holder(quantity=30)
        held = SubscriptionItemFactory(
            subscription=item.subscription,
            plan=targets["muckrock-request-pack"],
            quantity=3,
        )

        with pytest.raises(CommandError, match="already held"):
            run(actor=actor)

        held.refresh_from_db()
        assert held.quantity == 3

    def test_a_missing_comped_pack_is_named_up_front(self, actor):
        PlanPrice.objects.filter(
            plan__slug="muckrock-request-pack", label="comped"
        ).delete()
        block_holder(quantity=30, billing=False)

        with pytest.raises(CommandError, match="consolidate_stripe_products"):
            run(actor=actor)


@pytest.mark.django_db()
class TestWhatTheOrganizationReceives:
    """A line moves onto another plan's entitlements; the grant must hold."""

    def test_a_repoint_that_changes_the_grant_is_refused(self, targets, actor):
        item = line("professional-pre-paid")
        client = entitle(item.plan, {"base_requests": 20, "minimum_users": 1}).client
        entitle(
            targets["professional"],
            {"base_requests": 500, "minimum_users": 1},
            client=client,
        )

        out = StringIO()
        with pytest.raises(CommandError, match="failed"):
            call_command("backfill_plan_prices", stdout=out, actor=actor)

        assert "what this organization receives" in out.getvalue()
        item.refresh_from_db()
        assert item.plan_price is None

    def test_a_decided_change_is_allowed_and_noted(self, targets, actor):
        item = line("beta", billing=False)
        client = entitle(item.plan, {"base_requests": 5, "minimum_users": 1}).client
        entitle(
            targets["professional"],
            {"base_requests": 20, "minimum_users": 1},
            client=client,
        )

        out = run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is not None
        assert "grant changes as decided" in out

    def test_a_decided_change_may_not_lose_anything(self, targets, actor):
        item = line("beta", billing=False)
        client = entitle(item.plan, {"base_requests": 5, "minimum_users": 1}).client
        entitle(item.plan, {"base_ai_credits": 2000, "minimum_users": 1})
        entitle(
            targets["professional"],
            {"base_requests": 20, "minimum_users": 1},
            client=client,
        )

        with pytest.raises(CommandError, match="failed"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None

    def _organization_with_blocks(self, targets):
        """Production's Organization: 50 requests + 10 a block on MuckRock,
        5,000 credits + 500 a block on DocumentCloud; the pack carries only
        the requests."""
        item = block_holder(quantity=15)
        muckrock = entitle(
            item.plan,
            {"base_requests": 50, "requests_per_user": 10, "minimum_users": 5},
        )
        entitle(
            item.plan,
            {"base_ai_credits": 5000, "ai_credits_per_user": 500, "minimum_users": 5},
        )
        entitle(
            targets["muckrock-request-pack"],
            {"base_requests": 0, "requests_per_user": 10, "minimum_users": 0},
            client=muckrock.client,
        )
        return item

    def test_a_block_holder_keeps_its_requests_and_drops_the_credit_overage(
        self, targets, actor
    ):
        item = self._organization_with_blocks(targets)

        out = run(actor=actor)

        slug = item.subscription.organization.slug
        assert out.index(f"+ {slug}:") < out.index("block overage not carried")
        item.refresh_from_db()
        assert item.plan_price is not None

    def test_only_documentcloud_credits_may_be_dropped(self, targets, actor):
        """Another resource the pack does not carry is still refused."""
        item = self._organization_with_blocks(targets)
        entitle(
            item.plan,
            {"base_credits": 100, "credits_per_user": 10, "minimum_users": 5},
        )

        with pytest.raises(CommandError, match="failed"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None

    def test_a_pack_that_under_delivers_is_refused(self, targets, actor):
        item = self._organization_with_blocks(targets)
        pack = targets["muckrock-request-pack"].entitlements.get()
        pack.resources["requests_per_user"] = 5
        pack.save()

        with pytest.raises(CommandError, match="failed"):
            run(actor=actor)

        item.refresh_from_db()
        assert item.plan_price is None

    @pytest.mark.usefixtures("targets")
    def test_comped_blocks_that_grant_need_a_pack_up_front(self, actor):
        item = line(
            "muckrock-editorial-partner",
            billing=False,
            quantity=30,
            plan_fields={**GROUP, "base_price": 0, "price_per_user": 0},
        )
        entitle(
            item.plan,
            {"base_requests": 50, "requests_per_user": 10, "minimum_users": 5},
        )

        with pytest.raises(CommandError, match="PACK_DECOMPOSITION"):
            run(actor=actor)

    def test_a_flat_comped_plan_is_not_inflated(self, targets, actor):
        """Its flat grant would scale by the block count on Organization."""
        item = line(
            "premium-org-comp",
            billing=False,
            quantity=30,
            plan_fields={**GROUP, "base_price": 0, "price_per_user": 0},
        )
        client = entitle(item.plan, {"base_requests": 50, "minimum_users": 5}).client
        entitle(
            targets["organization"],
            {"base_requests": 50, "minimum_users": 5, "requests_per_user": 10},
            client=client,
        )

        run(actor=actor)

        item.refresh_from_db()
        assert item.quantity == 1
        assert not SubscriptionItem.objects.filter(plan__slug__in=PACK_SLUGS).exists()


@pytest.mark.django_db()
@pytest.mark.usefixtures("targets")
class TestWhatBlocksTheShapeMigration:
    def test_a_scaling_line_left_above_one_is_named(self, actor):
        item = line("professional", quantity=3, plan_fields={"base_price": 100})
        entitle(
            item.plan,
            {"base_requests": 20, "minimum_users": 1, "requests_per_user": 0},
        )

        out = run(actor=actor)

        assert "still above quantity 1" in out
        assert f"{item.subscription.organization.slug}: professional" in out

    def test_a_line_that_cannot_scale_is_not(self, actor):
        item = line("professional", quantity=3, plan_fields={"base_price": 100})
        entitle(item.plan, {"research_hours": 10})

        out = run(actor=actor)

        assert "still above quantity 1" not in out
