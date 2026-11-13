# Django
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError

# Standard Library
from datetime import date

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import PriceGrant, SubscriptionItem
from squarelet.organizations.payments.exceptions import SubscriptionError


@pytest.fixture(name="no_stripe")
def no_stripe_fixture(mocker):
    mocker.patch("squarelet.organizations.models.Subscription.start")
    mocker.patch(
        "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
    )


@pytest.fixture(name="tier")
def tier_fixture(plan_factory, plan_price_factory):
    plan = plan_factory(name="Granted Tier", for_individuals=False)
    plan_price_factory(plan=plan, interval="monthly", amount=10_000)
    plan_price_factory(plan=plan, interval="annual", amount=100_000)
    plan_price_factory(plan=plan, interval="monthly", label="nonprofit", amount=5_000)
    return plan


@pytest.fixture(name="deal")
def deal_fixture(tier, plan_price_factory):
    return plan_price_factory(plan=tier, interval="monthly", code="deal", amount=7_000)


@pytest.mark.django_db()
class TestAGrantIsBoughtInsteadOfTheListPrice:
    def _resolve(self, plan, organization, nonprofit=False, interval=None):
        _plan, price = SubscriptionItem.objects.resolve_purchase(
            plan, nonprofit, interval, organization
        )
        return price

    def test_the_granted_price_is_bought(self, tier, deal, price_grant_factory):
        grant = price_grant_factory(plan_price=deal)

        assert self._resolve(tier, grant.organization) == deal

    def test_it_beats_the_nonprofit_rate(self, tier, deal, price_grant_factory):
        grant = price_grant_factory(plan_price=deal)

        assert self._resolve(tier, grant.organization, nonprofit=True) == deal

    def test_only_at_its_own_interval(self, tier, deal, price_grant_factory):
        """Not the list price at another: that's a deal staff haven't made."""
        grant = price_grant_factory(plan_price=deal)

        assert self._resolve(tier, grant.organization, interval="annual") is None

    def test_it_follows_its_price_to_the_replacement_row(
        self, tier, deal, plan_price_factory, price_grant_factory
    ):
        grant = price_grant_factory(plan_price=deal)
        deal.active = False
        deal.save()
        replacement = plan_price_factory(plan=tier, code="deal", amount=7_500)

        assert self._resolve(tier, grant.organization) == replacement

    def test_an_ended_comp_is_not_bought(
        self, tier, plan_price_factory, price_grant_factory
    ):
        comp = plan_price_factory(plan=tier, label="comped", amount=0)
        grant = price_grant_factory(plan_price=comp, ends_on=date(2020, 1, 1))

        assert self._resolve(tier, grant.organization).amount == 10_000

    def test_a_comp_is_bought_on_its_last_day(
        self, tier, plan_price_factory, price_grant_factory
    ):
        comp = plan_price_factory(plan=tier, label="comped", amount=0)
        grant = price_grant_factory(plan_price=comp, ends_on=date.today())

        assert self._resolve(tier, grant.organization) == comp

    def test_only_for_its_own_organization(
        self, tier, deal, price_grant_factory, organization_factory
    ):
        price_grant_factory(plan_price=deal)

        assert self._resolve(tier, organization_factory()).amount == 10_000

    def test_a_retired_price_is_not_bought(self, tier, deal, price_grant_factory):
        grant = price_grant_factory(plan_price=deal)
        deal.active = False
        deal.save()

        assert self._resolve(tier, grant.organization).amount == 10_000


@pytest.mark.django_db()
@pytest.mark.usefixtures("no_stripe")
class TestTheLineCarriesTheGrant:
    def test_its_reason_and_approver(self, tier, deal, price_grant_factory):
        grant = price_grant_factory(plan_price=deal, reason="Board member's outlet")

        item, _ = SubscriptionItem.objects.start(
            organization=grant.organization, plan=tier
        )

        assert item.plan_price == deal
        assert item.granted_reason == "Board member's outlet"
        assert item.granted_by == grant.granted_by

    def test_a_comp_ends_when_the_grant_says(
        self, tier, plan_price_factory, price_grant_factory
    ):
        comp = plan_price_factory(plan=tier, label="comped", amount=0)
        grant = price_grant_factory(plan_price=comp, ends_on=date(2027, 6, 30))

        item, _ = SubscriptionItem.objects.start(
            organization=grant.organization, plan=tier
        )

        assert item.is_free
        assert item.ends_on == date(2027, 6, 30)

    def test_a_comp_now_charged_for_takes_no_end_date(
        self, tier, plan_price_factory, price_grant_factory
    ):
        """The deal's terms are now on a paid row; a paid line can't end."""
        comp = plan_price_factory(plan=tier, code="board", amount=0)
        grant = price_grant_factory(plan_price=comp, ends_on=date(2099, 1, 1))
        comp.active = False
        comp.save()
        plan_price_factory(plan=tier, code="board", amount=1_000)

        item, _ = SubscriptionItem.objects.start(
            organization=grant.organization, plan=tier
        )

        assert item.plan_price.amount == 1_000
        assert item.ends_on is None

    def test_a_list_price_purchase_carries_nothing(
        self, tier, deal, price_grant_factory, organization_factory
    ):
        price_grant_factory(plan_price=deal)

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=tier
        )

        assert item.granted_reason == ""
        assert item.granted_by is None


@pytest.mark.django_db()
class TestWhatCanBeGranted:
    def test_a_retired_price_cannot(self, deal, price_grant_factory):
        deal.active = False
        deal.save()

        with pytest.raises(ValidationError, match="retired"):
            price_grant_factory.build(plan_price=deal).full_clean()

    def test_a_paid_price_cannot_end_on_a_date(self, deal, price_grant_factory):
        grant = price_grant_factory.build(plan_price=deal, ends_on=date(2027, 1, 1))

        with pytest.raises(ValidationError, match="free price"):
            grant.full_clean()

    def test_an_end_date_already_past_cannot(
        self, tier, plan_price_factory, price_grant_factory
    ):
        comp = plan_price_factory(plan=tier, label="comped", amount=0)
        grant = price_grant_factory.build(plan_price=comp, ends_on=date(2020, 1, 1))

        with pytest.raises(ValidationError, match="already passed"):
            grant.full_clean()

    def test_a_free_one_can(self, tier, plan_price_factory, price_grant_factory):
        comp = plan_price_factory(plan=tier, label="comped", amount=0)

        price_grant_factory(plan_price=comp, ends_on=date(2027, 1, 1)).full_clean()

    def test_one_per_plan_and_interval(
        self, tier, deal, plan_price_factory, price_grant_factory
    ):
        grant = price_grant_factory(plan_price=deal)
        other = plan_price_factory(
            plan=tier, interval="monthly", code="other", amount=6_000
        )
        second = price_grant_factory.build(
            organization=grant.organization,
            plan_price=other,
            granted_by=grant.granted_by,
        )

        with pytest.raises(ValidationError, match="already has a price"):
            second.full_clean()

    def test_another_interval_is_another_grant(
        self, tier, deal, plan_price_factory, price_grant_factory
    ):
        grant = price_grant_factory(plan_price=deal)
        annual = plan_price_factory(
            plan=tier, interval="annual", code="deal", amount=70_000
        )

        price_grant_factory(
            organization=grant.organization,
            plan_price=annual,
            granted_by=grant.granted_by,
        ).full_clean()


@pytest.mark.django_db()
def test_the_admin_names_whoever_adds_a_grant_as_its_approver(rf, user_factory):
    staff = user_factory(is_staff=True)
    request = rf.get("/")
    request.user = staff

    initial = site.get_model_admin(PriceGrant).get_changeform_initial_data(request)

    assert initial["granted_by"] == staff.pk


@pytest.mark.django_db()
class TestMergingOrganizations:
    def test_the_merged_orgs_grants_come_across(
        self, deal, price_grant_factory, organization_factory, user_factory
    ):
        survivor = organization_factory()
        grant = price_grant_factory(plan_price=deal)

        survivor.merge(grant.organization, user_factory())

        assert list(survivor.price_grants.all()) == [grant]

    def test_but_the_survivors_own_deal_on_that_plan_stands(
        self, tier, deal, plan_price_factory, price_grant_factory, user_factory
    ):
        own = price_grant_factory(plan_price=deal)
        other = plan_price_factory(
            plan=tier, interval="monthly", code="other", amount=6_000
        )
        merged = price_grant_factory(plan_price=other).organization

        own.organization.merge(merged, user_factory())

        assert list(own.organization.price_grants.all()) == [own]
        assert not merged.price_grants.exists()


@pytest.mark.django_db()
@pytest.mark.usefixtures("no_stripe")
def test_a_comp_already_held_is_not_bought_again(
    tier, plan_price_factory, price_grant_factory, user_factory
):
    comp = plan_price_factory(plan=tier, label="comped", amount=0)
    grant = price_grant_factory(plan_price=comp)
    SubscriptionItem.objects.start(organization=grant.organization, plan=tier)

    with pytest.raises(SubscriptionError, match="already has"):
        grant.organization.add_subscription(tier, None, user_factory())


@pytest.mark.django_db()
class TestChangingTierInPlace:
    @pytest.fixture(name="other_tier")
    def other_tier_fixture(self, plan_factory, plan_price_factory):
        plan = plan_factory(name="Other Tier", for_individuals=False)
        plan_price_factory(plan=plan, interval="monthly", amount=20_000)
        return plan

    @pytest.fixture(autouse=True)
    def no_stripe_sync(self, mocker):
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")

    def test_a_deal_on_the_new_tier_is_billed(
        self,
        tier,
        other_tier,
        plan_price_factory,
        subscription_item_factory,
        price_grant_factory,
    ):
        line = subscription_item_factory(plan=tier)
        deal = plan_price_factory(plan=other_tier, label="partner", amount=15_000)
        grant = price_grant_factory(
            organization=line.subscription.organization, plan_price=deal
        )

        line.modify(other_tier)

        line.refresh_from_db()
        assert line.plan_price == deal
        assert line.granted_reason == grant.reason

    def test_a_nonprofit_takes_its_deal_where_there_is_no_nonprofit_rate(
        self,
        tier,
        other_tier,
        plan_price_factory,
        subscription_item_factory,
        price_grant_factory,
    ):
        line = subscription_item_factory(
            plan=tier, plan_price=tier.prices.get(label="nonprofit")
        )
        deal = plan_price_factory(plan=other_tier, label="partner", amount=15_000)
        price_grant_factory(
            organization=line.subscription.organization, plan_price=deal
        )

        line.modify(other_tier)

        line.refresh_from_db()
        assert line.plan_price == deal

    def test_leaving_the_deals_tier_leaves_its_reason(
        self,
        tier,
        other_tier,
        plan_price_factory,
        subscription_item_factory,
        price_grant_factory,
    ):
        partner = plan_price_factory(plan=tier, label="partner", amount=9_000)
        line = subscription_item_factory(plan=tier, plan_price=partner)
        grant = price_grant_factory(
            organization=line.subscription.organization, plan_price=partner
        )
        line.granted_reason = grant.reason
        line.granted_by = grant.granted_by
        line.save()

        line.modify(other_tier)

        line.refresh_from_db()
        assert line.plan_price.amount == 20_000
        assert line.granted_reason == ""
        assert line.granted_by is None
