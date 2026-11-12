"""Checkout for an organization staff have given a special price."""

# pylint: disable=too-many-positional-arguments

# Standard Library
from datetime import date

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations import views
from squarelet.organizations.models import Organization
from squarelet.organizations.plan_mapping import SUNLIGHT_SERVICE_SLUG
from squarelet.services.tests.factories import ServiceFactory


@pytest.fixture(name="admin")
def admin_fixture(user_factory):
    return user_factory()


@pytest.fixture(name="organization")
def organization_fixture(organization_factory, admin):
    # No card on file.
    return organization_factory(admins=[admin])


@pytest.fixture(name="add_subscription")
def add_subscription_fixture(mocker):
    return mocker.patch.object(Organization, "add_subscription")


@pytest.mark.django_db()
class TestCheckingOutAtTheGrantedPrice(ViewTestMixin):
    view = views.PlanCheckout
    url = "/organizations/{slug}/plans/{plan_slug}/{interval}/"

    def call(self, rf, admin, organization, plan, data=None):
        return self.call_view(
            rf,
            admin,
            data,
            slug=organization.slug,
            plan_slug=plan.slug,
            interval="monthly",
        )

    def test_the_page_quotes_the_deal(
        self, rf, admin, organization, plan_price_factory, price_grant_factory
    ):
        plan = plan_price_factory(plan__name="Tier", amount=10_000).plan
        deal = plan_price_factory(plan=plan, code="deal", amount=7_000)
        price_grant_factory(organization=organization, plan_price=deal)

        content = self.call(rf, admin, organization, plan).render().content.decode()

        assert "<strong>$70</strong>" in content
        assert "<s>$100</s>" in content

    def test_a_comp_needs_no_card(
        self, rf, admin, organization, plan_price_factory, price_grant_factory
    ):
        plan = plan_price_factory(plan__name="Tier", amount=10_000).plan
        comp = plan_price_factory(plan=plan, label="comped", amount=0)
        price_grant_factory(organization=organization, plan_price=comp)

        content = self.call(rf, admin, organization, plan).render().content.decode()

        assert 'id="card-form"' not in content
        assert "data-has-card" in content

    def test_a_comp_is_bought_without_a_card(
        self,
        rf,
        admin,
        organization,
        plan_price_factory,
        price_grant_factory,
        add_subscription,
    ):
        plan = plan_price_factory(plan__name="Tier", amount=10_000).plan
        comp = plan_price_factory(plan=plan, label="comped", amount=0)
        price_grant_factory(organization=organization, plan_price=comp)

        self.call(rf, admin, organization, plan, data={})

        add_subscription.assert_called_once()

    def test_a_paid_deal_still_needs_one(
        self,
        rf,
        admin,
        organization,
        plan_price_factory,
        price_grant_factory,
        add_subscription,
    ):
        plan = plan_price_factory(plan__name="Tier", amount=10_000).plan
        deal = plan_price_factory(plan=plan, code="deal", amount=7_000)
        price_grant_factory(organization=organization, plan_price=deal)

        self.call(rf, admin, organization, plan, data={})

        add_subscription.assert_not_called()

    def test_an_annual_comp_offers_no_invoice(
        self, rf, admin, organization, plan_price_factory, price_grant_factory
    ):
        plan = plan_price_factory(plan__name="Tier", interval="annual").plan
        comp = plan_price_factory(
            plan=plan, interval="annual", label="comped", amount=0
        )
        price_grant_factory(organization=organization, plan_price=comp)

        response = self.call_view(
            rf, admin, slug=organization.slug, plan_slug=plan.slug, interval="annual"
        )

        assert "Invoiced today" not in response.render().content.decode()


@pytest.mark.django_db()
class TestADealSkipsTheSunlightCap(ViewTestMixin):
    view = views.PlanCheckout
    url = "/organizations/{slug}/plans/{plan_slug}/{interval}/"

    @pytest.fixture(name="sunlight")
    def sunlight_fixture(self, plan_price_factory, settings):
        settings.MAX_SUNLIGHT_SUBSCRIPTIONS = 0
        return plan_price_factory(
            plan__name="Sunlight Tier",
            plan__service=ServiceFactory(slug=SUNLIGHT_SERVICE_SLUG),
            plan__wix=True,
            amount=0,
            label="comped",
        ).plan

    def call(self, rf, admin, organization, plan, data=None):
        return self.call_view(
            rf,
            admin,
            data,
            slug=organization.slug,
            plan_slug=plan.slug,
            interval="monthly",
        )

    def test_the_page_offers_to_subscribe(
        self, rf, admin, organization, sunlight, price_grant_factory
    ):
        price_grant_factory(organization=organization, plan_price=sunlight.prices.get())

        content = self.call(rf, admin, organization, sunlight).render().content

        assert b"Subscribe to this plan" in content
        assert b"Join the waitlist" not in content

    def test_it_is_bought_not_waitlisted(
        self,
        rf,
        admin,
        organization,
        sunlight,
        price_grant_factory,
        add_subscription,
        mocker,
    ):
        add_to_waitlist = mocker.patch("squarelet.payments.views.add_to_waitlist")
        price_grant_factory(organization=organization, plan_price=sunlight.prices.get())

        self.call(rf, admin, organization, sunlight, data={})

        add_subscription.assert_called_once()
        add_to_waitlist.delay.assert_not_called()

    def test_an_ended_comp_waits_like_anyone_else(
        self, rf, admin, organization, sunlight, price_grant_factory
    ):
        price_grant_factory(
            organization=organization,
            plan_price=sunlight.prices.get(),
            ends_on=date(2020, 1, 1),
        )
        sunlight.prices.update(label="standard", amount=5_000)

        content = self.call(rf, admin, organization, sunlight).render().content

        assert b"Join the waitlist" in content


@pytest.mark.django_db()
class TestTheCheckoutLinkGoesToTheDeal(ViewTestMixin):
    view = views.PlanCheckoutRedirect
    url = "/organizations/{slug}/plans/{plan_slug}/"

    def test_its_interval_not_the_lists(
        self, rf, admin, organization, plan_price_factory, price_grant_factory
    ):
        plan = plan_price_factory(plan__name="Tier", amount=10_000).plan
        plan_price_factory(plan=plan, interval="annual", amount=100_000)
        deal = plan_price_factory(plan=plan, code="deal", amount=7_000)
        price_grant_factory(organization=organization, plan_price=deal)

        response = self.call_view(
            rf, admin, slug=organization.slug, plan_slug=plan.slug
        )

        assert response.url.endswith(f"/plans/{plan.slug}/monthly/")
