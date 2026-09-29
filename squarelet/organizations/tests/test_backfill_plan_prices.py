# Django
from django.core.management import call_command
from django.core.management.base import CommandError

# Standard Library
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Plan, PlanPrice, Subscription
from squarelet.organizations.plan_mapping import LEGACY_PLAN_MAP
from squarelet.organizations.tests.factories import (
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
        PlanPriceFactory(
            plan=plans[slug],
            interval=interval,
            label=label,
            code=code,
            amount=0 if label == "comped" else 10_000,
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

    def test_a_line_holding_blocks_is_refused(self, actor):
        line(
            "organization",
            quantity=30,
            plan_fields={"for_groups": True, "minimum_users": 5, "price_per_user": 10},
        )

        with pytest.raises(CommandError, match="resource blocks"):
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

    def test_a_second_run_leaves_migrated_lines_alone(self, actor):
        item = line("professional")
        run(actor=actor)

        out = run(actor=actor)

        assert "0 migrated, 1 already done" in out
        item.refresh_from_db()
        assert item.plan_price.label == "standard"

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
