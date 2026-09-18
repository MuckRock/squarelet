"""Integration tests against a real Stripe sandbox.

Deselected from the ordinary suite by the `stripe` marker, which
`pytest.ini` excludes by default; `inv test-stripe` selects it.  The sandbox
key is an ordinary setting, read from the Django env file.

These exist because the unit suite cannot see the failures that have
actually mattered here.  It mocks Stripe, and the factories set the fields
production code failed to write - `stripe_item_id` was read in three places,
written in none, and 1,700 tests stayed green.  Every assertion below reads
Stripe's own state back after driving the app's real code paths, so what is
being checked is what Stripe ends up holding, not what we believe we sent.
"""

# A fixture and the parameter that receives it necessarily share a name.
# pylint: disable=redefined-outer-name

# Django
from django.core.management import call_command
from django.utils.text import slugify

# Standard Library
from uuid import uuid4

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import Subscription, SubscriptionItem

pytestmark = [pytest.mark.stripe, pytest.mark.django_db()]


@pytest.fixture(autouse=True)
def sandbox(settings):
    """Point the app and this module at the sandbox, and tidy up after.

    `get_payment_provider()` reads the setting on every call and assigns
    `stripe.api_key` as it builds the provider, so overriding the setting is
    enough to move the whole app across.
    """
    key = settings.STRIPE_SANDBOX_SECRET_KEY
    # Selecting these without a sandbox to point them at is a mistake worth
    # naming, rather than a wall of Stripe authentication errors.
    assert key, (
        "STRIPE_SANDBOX_SECRET_KEY is not set.  Create a sandbox in the "
        "Stripe dashboard and put its secret key in the Django env file."
    )
    assert not key.startswith("sk_live"), (
        "STRIPE_SANDBOX_SECRET_KEY is a live key.  These create and delete "
        "subscriptions - point them at a sandbox."
    )
    settings.STRIPE_SECRET_KEY = key
    stripe.api_key = key

    created = {"subscriptions": [], "customers": [], "plans": []}
    yield created

    # Subscriptions first: a customer cannot be deleted out from under one.
    for subscription_id in created["subscriptions"]:
        try:
            stripe.Subscription.delete(subscription_id)
        except stripe.StripeError:
            pass
    for customer_id in created["customers"]:
        try:
            stripe.Customer.delete(customer_id)
        except stripe.StripeError:
            pass
    for plan in created["plans"]:
        try:
            plan.delete_stripe_plan()
        except stripe.StripeError:
            pass


def paid_plan(plan_factory, sandbox, price=25):
    """A plan that exists on Stripe, named uniquely for this run.

    Unique because Stripe objects outlive the test: reusing a name would
    silently adopt a plan a previous run created at a different price, and
    the assertions here are about amounts.

    This is the one place that knows *what* the branch bills against.  Once
    the stack moves subscriptions onto PlanPrice, this becomes
    `PlanPrice.ensure_stripe_price()`; nothing else below should need to
    change.
    """
    name = f"Sandbox {uuid4().hex[:8]}"
    plan = plan_factory(
        name=name, slug=slugify(name), base_price=price, price_per_user=0
    )
    plan.make_stripe_plan()
    sandbox["plans"].append(plan)
    return plan


def tiered_plan(plan_factory, sandbox):
    """A legacy group plan, billed the way the real ones are.

    `billing_scheme: tiered` with `tiers_mode: graduated`: a flat amount up
    to `minimum_users`, then per block beyond it.  Quantity *selects* a tier
    here.  Every new PlanPrice is `per_unit`, where quantity *multiplies* -
    reading one as the other overcharges a five-seat subscriber fivefold,
    which is the largest single risk in this migration and the reason these
    assert amounts rather than price ids.
    """
    name = f"Sandbox Tiered {uuid4().hex[:8]}"
    plan = plan_factory(
        name=name,
        slug=slugify(name),
        for_groups=True,
        minimum_users=5,
        base_price=100,
        price_per_user=10,
    )
    plan.make_stripe_plan()
    sandbox["plans"].append(plan)
    return plan


def invoice_total(subscription_id):
    """What Stripe says the customer is actually being charged, in cents."""
    live = stripe.Subscription.retrieve(subscription_id, expand=["latest_invoice"])
    return live["latest_invoice"]["total"]


def stripe_invoice_ids(subscription_id):
    """Every invoice Stripe has raised against this subscription."""
    return {
        invoice["id"]
        for invoice in stripe.Invoice.list(
            subscription=subscription_id
        ).auto_paging_iter()
    }


def with_card(organization, sandbox):
    """Give the org a Stripe customer holding a usable test card.

    And an email address: Stripe refuses `send_invoice` without one, since
    that is where it would send the invoice.
    """
    customer = organization.customer()
    customer.save_card("tok_visa")
    stripe_customer = customer.stripe_customer
    stripe.Customer.modify(stripe_customer.id, email=f"{organization.slug}@example.com")
    sandbox["customers"].append(stripe_customer.id)
    return customer


def start(organization, plan, sandbox, **kwargs):
    """Add a line through the app, and register it for cleanup."""
    item, _ = SubscriptionItem.objects.start(organization, plan, **kwargs)
    subscription_id = item.subscription.subscription_id
    if subscription_id and subscription_id not in sandbox["subscriptions"]:
        sandbox["subscriptions"].append(subscription_id)
    return item


def stripe_prices(subscription_id):
    """The set of Price ids Stripe currently bills on this subscription."""
    live = stripe.Subscription.retrieve(subscription_id)
    return {i["price"]["id"] for i in live["items"]["data"]}


class TestAddingASecondPlan:
    """The failure a customer hits first after the split deploys."""

    def test_the_existing_line_is_updated_not_re_added(
        self, organization_factory, plan_factory, sandbox
    ):
        """An unidentified line is sent with no id, which means "add".

        Stripe then refuses - "an existing Subscription Item is already using
        that Price" - or duplicates the line and bills for both.  Every line
        migrated from before the split starts out unidentified.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        first = start(organization, paid_plan(plan_factory, sandbox), sandbox)

        # The state every pre-split line is in: 0084 adds the column empty
        # and has nothing to populate it from.
        SubscriptionItem.objects.filter(pk=first.pk).update(stripe_item_id="")

        second_plan = paid_plan(plan_factory, sandbox, price=40)
        start(organization, second_plan, sandbox)

        subscription_id = first.subscription.subscription_id
        assert stripe_prices(subscription_id) == {
            first.plan.stripe_id,
            second_plan.stripe_id,
        }

    def test_a_new_subscription_starts_identified(
        self, organization_factory, plan_factory, sandbox
    ):
        """Stripe hands back the item ids when it creates the subscription.

        Dropping them left every new subscriber in the state the backfill
        command exists to repair, so `audit_subscriptions` reported each of
        their lines as missing on Stripe - which is the check the runbook
        tells you to trust after deploying.
        """
        organization = organization_factory()
        with_card(organization, sandbox)

        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)

        item.refresh_from_db()
        assert item.stripe_item_id.startswith("si_")

    def test_the_line_learns_its_stripe_id(
        self, organization_factory, plan_factory, sandbox
    ):
        """Otherwise the next change repeats the whole problem."""
        organization = organization_factory()
        with_card(organization, sandbox)
        first = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        SubscriptionItem.objects.filter(pk=first.pk).update(stripe_item_id="")

        start(organization, paid_plan(plan_factory, sandbox, price=40), sandbox)

        first.refresh_from_db()
        assert first.stripe_item_id.startswith("si_")


class TestGoingFreeAndBack:
    """An id has to name an item on the subscription that exists now."""

    def test_a_line_does_not_keep_an_id_from_a_deleted_subscription(
        self, organization_factory, plan_factory, sandbox
    ):
        """Downgrading deletes the Stripe subscription the ids referred to.

        Kept, they would be sent to whichever subscription is started next,
        which has never heard of them - Stripe rejects the whole call, and
        the line can never be removed.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        free_name = f"Sandbox Free {uuid4().hex[:8]}"
        item.modify(
            plan_factory(
                name=free_name,
                slug=slugify(free_name),
                base_price=0,
                price_per_user=0,
            )
        )

        item.refresh_from_db()
        assert item.stripe_item_id == ""

        # And the next subscription identifies itself from scratch.
        revived = start(organization, paid_plan(plan_factory, sandbox), sandbox)

        revived.refresh_from_db()
        assert revived.stripe_item_id.startswith("si_")
        assert stripe_prices(revived.subscription.subscription_id) == {
            revived.plan.stripe_id
        }


class TestChangingAPlan:
    """`modify_subscription` has no caller today and must work when it does."""

    def test_the_price_is_swapped_on_the_same_subscription(
        self, organization_factory, plan_factory, sandbox
    ):
        """In place, so the billing anchor and its prorations survive."""
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        subscription_id = item.subscription.subscription_id
        new_plan = paid_plan(plan_factory, sandbox, price=40)

        item.modify(new_plan)

        assert item.subscription.subscription_id == subscription_id
        assert stripe_prices(subscription_id) == {new_plan.stripe_id}

    def test_moving_to_a_free_plan_stops_the_billing(
        self, organization_factory, plan_factory, sandbox
    ):
        """The last paid line going free has to end the subscription."""
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        subscription_id = item.subscription.subscription_id
        free_name = f"Sandbox Free {uuid4().hex[:8]}"

        item.modify(
            plan_factory(
                name=free_name,
                slug=slugify(free_name),
                base_price=0,
                price_per_user=0,
            )
        )

        assert stripe.Subscription.retrieve(subscription_id).status == "canceled"
        item.subscription.refresh_from_db()
        assert item.subscription.subscription_id == ""


class TestWhatTheCustomerIsCharged:
    """Identity is not enough: the amount is the thing that can be wrong."""

    def test_a_tiered_plan_at_its_minimum_bills_the_flat_amount(
        self, organization_factory, plan_factory, sandbox
    ):
        """Quantity selects the tier; it does not multiply it.

        Five seats on a $100 plan with a five-seat minimum is $100, not
        $500.  Most group subscribers sit exactly here.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(
            organization, tiered_plan(plan_factory, sandbox), sandbox, quantity=5
        )

        assert invoice_total(item.subscription.subscription_id) == 100_00

    def test_a_tiered_plan_above_its_minimum_bills_per_block(
        self, organization_factory, plan_factory, sandbox
    ):
        """$100 base, then $10 for each block past the fifth."""
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(
            organization, tiered_plan(plan_factory, sandbox), sandbox, quantity=7
        )

        assert invoice_total(item.subscription.subscription_id) == 120_00


class TestCancellingOnStripe:
    """The only subscription action the interface actually offers."""

    def test_cancel_then_resubscribe_round_trips(
        self, organization_factory, plan_factory, sandbox
    ):
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        subscription = item.subscription

        subscription.cancel()

        live = stripe.Subscription.retrieve(subscription.subscription_id)
        assert live["cancel_at_period_end"] is True
        assert subscription.cancel_at is not None

        subscription.uncancel()

        live = stripe.Subscription.retrieve(subscription.subscription_id)
        assert live["cancel_at_period_end"] is False
        assert subscription.cancel_at is None

    def test_a_pending_cancellation_survives_adding_a_plan(
        self, organization_factory, plan_factory, sandbox
    ):
        """Touching a line must not quietly re-bill a leaving customer.

        `stripe_modify` sends cancel_at_period_end on every call, so sending
        the wrong value reverses a cancellation on Stripe - where the money
        is - with nothing in our own records to show it happened.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        item.subscription.cancel()

        start(organization, paid_plan(plan_factory, sandbox, price=40), sandbox)

        live = stripe.Subscription.retrieve(item.subscription.subscription_id)
        assert live["cancel_at_period_end"] is True

    def test_a_free_line_is_never_described_to_stripe(
        self, organization_factory, plan_factory, sandbox
    ):
        """A free plan has no Stripe counterpart to name.

        Naming one fails the whole call, paid lines included - so the free
        line is dropped, and Stripe must end up holding only the paid one.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        paid = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        free_name = f"Sandbox Free {uuid4().hex[:8]}"
        start(
            organization,
            plan_factory(
                name=free_name,
                slug=slugify(free_name),
                base_price=0,
                price_per_user=0,
            ),
            sandbox,
        )

        assert stripe_prices(paid.subscription.subscription_id) == {paid.plan.stripe_id}


class TestProratedInvoicing:
    """When the customer is billed for a plan added mid-period.

    Stripe's default writes the proration onto the *upcoming* invoice and
    raises nothing now, so a card payer who added a plan saw no charge and
    no invoice until the next cycle.  `Subscription.proration_behavior`
    splits the two audiences; both halves are worth pinning, because each
    is only visible against real Stripe.
    """

    def test_a_card_payer_is_invoiced_for_the_added_plan_now(
        self, organization_factory, plan_factory, sandbox
    ):
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        subscription_id = item.subscription.subscription_id
        before = stripe_invoice_ids(subscription_id)

        start(organization, paid_plan(plan_factory, sandbox, price=40), sandbox)

        added = stripe_invoice_ids(subscription_id) - before
        assert len(added) == 1
        invoice_id = added.pop()
        assert stripe.Invoice.retrieve(invoice_id)["total"] > 0
        # The row the organization's billing page reads.  Stripe raising
        # the invoice is only half of it: `settle_added_line` has to write
        # it down, or the charge happens with nothing here to show it.
        assert organization.invoices.filter(invoice_id=invoice_id).exists()

    def test_an_invoiced_organization_gets_no_second_invoice(
        self, organization_factory, plan_factory, sandbox
    ):
        """Their change rides on the next scheduled invoice.

        `always_invoice` would email them a separate one, with its own due
        date, part-way through a term they have already been billed for.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        name = f"Sandbox Annual {uuid4().hex[:8]}"
        plan = plan_factory(
            name=name,
            slug=slugify(name),
            annual=True,
            base_price=300,
            price_per_user=0,
        )
        plan.make_stripe_plan()
        sandbox["plans"].append(plan)
        item = start(organization, plan, sandbox, payment_method="invoice")
        subscription_id = item.subscription.subscription_id
        before = stripe_invoice_ids(subscription_id)

        second_name = f"Sandbox Annual {uuid4().hex[:8]}"
        second = plan_factory(
            name=second_name,
            slug=slugify(second_name),
            annual=True,
            base_price=120,
            price_per_user=0,
        )
        second.make_stripe_plan()
        sandbox["plans"].append(second)
        start(organization, second, sandbox, payment_method="invoice")

        assert stripe_invoice_ids(subscription_id) == before


class TestAnnualInvoicing:
    def test_an_invoiced_annual_plan_is_collected_by_invoice(
        self, organization_factory, plan_factory, sandbox
    ):
        """A different branch of `start`, and the one finding 6 was about.

        Every other test here runs monthly and charged automatically, so
        nothing else would notice `collection_method` being decided wrongly.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        name = f"Sandbox Annual {uuid4().hex[:8]}"
        plan = plan_factory(
            name=name,
            slug=slugify(name),
            annual=True,
            base_price=300,
            price_per_user=0,
        )
        plan.make_stripe_plan()
        sandbox["plans"].append(plan)

        item = start(organization, plan, sandbox, payment_method="invoice")

        live = stripe.Subscription.retrieve(item.subscription.subscription_id)
        assert live["collection_method"] == "send_invoice"
        assert live["days_until_due"] == 30
        assert item.subscription.collection_method == "send_invoice"


class TestAddingToAnAnnualSubscription:
    def test_a_card_payer_keeps_being_charged_automatically(
        self, organization_factory, plan_factory, sandbox
    ):
        """Adding a plan must not change how the customer pays.

        `stripe_modify` derived the collection method from the interval, so
        any annual subscriber was pushed to `send_invoice` - silently
        switching a card payer to being invoiced, while the local row went
        on saying they were charged automatically.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        name = f"Sandbox Annual Card {uuid4().hex[:8]}"
        annual = plan_factory(
            name=name,
            slug=slugify(name),
            annual=True,
            base_price=300,
            price_per_user=0,
        )
        annual.make_stripe_plan()
        sandbox["plans"].append(annual)
        item = start(organization, annual, sandbox)
        subscription_id = item.subscription.subscription_id
        assert (
            stripe.Subscription.retrieve(subscription_id)["collection_method"]
            == "charge_automatically"
        )

        second = f"Sandbox Annual Card 2 {uuid4().hex[:8]}"
        other = plan_factory(
            name=second,
            slug=slugify(second),
            annual=True,
            base_price=400,
            price_per_user=0,
        )
        other.make_stripe_plan()
        sandbox["plans"].append(other)
        start(organization, other, sandbox)

        live = stripe.Subscription.retrieve(subscription_id)
        assert live["collection_method"] == "charge_automatically"
        assert stripe_prices(subscription_id) == {annual.stripe_id, other.stripe_id}


class TestCollectionMethodComesFromStripe:
    """How Stripe collects is Stripe's fact, not one we can infer."""

    def test_a_wrong_local_value_is_corrected_on_the_next_interaction(
        self, organization_factory, plan_factory, sandbox
    ):
        """`0084` guesses it from `plan.annual`; the runtime keys it on the
        payment method.  An annual subscriber paying by card was migrated as
        `send_invoice` and stopped matching the lookup that finds their
        subscription, so the next plan they bought opened a second one.
        """
        organization = organization_factory()
        with_card(organization, sandbox)
        item = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        subscription = item.subscription
        assert subscription.collection_method == "charge_automatically"

        # The state the migration's guess leaves an annual card payer in.
        Subscription.objects.filter(pk=subscription.pk).update(
            collection_method="send_invoice"
        )
        subscription.refresh_from_db()

        subscription.cache_stripe_subscription_fields(
            stripe.Subscription.retrieve(subscription.subscription_id)
        )

        assert subscription.collection_method == "charge_automatically"


class TestTheBackfillCommand:
    """It runs on production at release, over every existing subscriber."""

    def test_it_identifies_every_unidentified_line(
        self, organization_factory, plan_factory, sandbox
    ):
        organization = organization_factory()
        with_card(organization, sandbox)
        first = start(organization, paid_plan(plan_factory, sandbox), sandbox)
        second = start(
            organization, paid_plan(plan_factory, sandbox, price=40), sandbox
        )
        SubscriptionItem.objects.filter(pk__in=[first.pk, second.pk]).update(
            stripe_item_id=""
        )

        call_command("backfill_stripe_item_ids")

        for line in (first, second):
            line.refresh_from_db()
            assert line.stripe_item_id.startswith("si_")
