# Django
from django.template.loader import render_to_string
from django.urls import reverse

# Standard Library
import datetime
from datetime import date

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import InvitationRole
from squarelet.organizations.tests.factories import (
    InvitationFactory,
    PlanFactory,
    SubscriptionItemFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestInvitationListItem:
    """Rendering tests for organizations/invitation_list_item.html"""

    template = "organizations/invitation_list_item.html"

    def test_invitation_with_user_shows_name_and_username(self):
        user = UserFactory(username="jdoe", name="Jane Doe")
        invitation = InvitationFactory(user=user, email="jane@example.com")

        html = render_to_string(self.template, {"invitation": invitation})

        assert "Jane Doe" in html
        assert ">jdoe<" in html
        # Email must not leak when a user is attached
        assert "jane@example.com" not in html

    def test_invitation_with_user_falls_back_to_username_when_name_blank(self):
        user = UserFactory(username="jdoe", name="")
        invitation = InvitationFactory(user=user, email="jane@example.com")

        html = render_to_string(self.template, {"invitation": invitation})

        assert "jdoe" in html
        assert "jane@example.com" not in html

    def test_invitation_with_email_only_shows_email(self):
        invitation = InvitationFactory(user=None, email="invited@example.com")

        html = render_to_string(self.template, {"invitation": invitation})

        assert "invited@example.com" in html

    def test_invitation_without_user_or_email_shows_generated_link(self):
        invitation = InvitationFactory(user=None, email="")

        html = render_to_string(self.template, {"invitation": invitation})

        assert "Generated link" in html

    def test_admin_badge_rendered_for_user_invitation(self):
        user = UserFactory(username="jdoe", name="Jane Doe")
        invitation = InvitationFactory(
            user=user, email="jane@example.com", role=InvitationRole.admin
        )

        html = render_to_string(self.template, {"invitation": invitation})

        assert "Admin" in html


@pytest.mark.django_db
class TestPlanCard:
    """Rendering tests for organizations/includes/plan_card.html"""

    template = "organizations/includes/plan_card.html"

    def _render(self, **context):
        return render_to_string(
            self.template,
            {
                "subject": "organizations",
                "subject_slug": "acme",
                "subscriptions": [],
                "subscription_benefits": [],
                "inherited_orgs": [],
                "inherited_benefits": [],
                **context,
            },
        )

    def test_a_renewing_line_shows_when_it_renews(self, plan_factory):
        """The date lives on the subscription; the card lists lines.

        Reading `current_period_end` off a line - where it stopped being
        after the split moved it to the parent - resolves to the empty
        string rather than raising, so the renewal date simply stopped
        appearing on the organization and user pages.
        """
        item = SubscriptionItemFactory(
            plan=plan_factory(name="Renewing Plan"),
            subscription__current_period_end=datetime.datetime(
                2026, 10, 20, 12, tzinfo=datetime.timezone.utc
            ),
        )

        html = self._render(org=item.subscription.organization, subscriptions=[item])

        assert "Renews" in html
        assert "October 20, 2026" in html

    def test_a_cancelled_line_shows_when_it_ends_instead(self, plan_factory):
        item = SubscriptionItemFactory(
            plan=plan_factory(name="Ending Plan"),
            cancelled=True,
            cancel_at=date(2026, 10, 20),
            subscription__current_period_end=datetime.datetime(
                2026, 10, 20, 12, tzinfo=datetime.timezone.utc
            ),
        )

        html = self._render(org=item.subscription.organization, subscriptions=[item])

        assert "Ends October 20, 2026" in html
        assert "Renews" not in html

    def test_own_benefits_listed_with_own_plans(
        self, organization_factory, plan_factory
    ):
        """Owned plans and the benefits they add up to render together"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])

        html = self._render(
            subscriptions=list(org.subscription_items.all()),
            subscription_benefits=["100 requests each month"],
        )

        assert "Org Plan" in html
        assert "Benefits" in html
        assert "100 requests each month" in html

    def test_own_and_inherited_benefits_render_in_separate_cards(
        self, organization_factory, plan_factory
    ):
        """Benefits the org pays for are not listed alongside inherited ones"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])
        parent = organization_factory(name="Parent Org")

        html = self._render(
            subscriptions=list(org.subscription_items.all()),
            subscription_benefits=["Own benefit"],
            inherited_orgs=[parent],
            inherited_benefits=["Inherited benefit"],
        )

        own_card, inherited_card = html.split("as an affiliate of")
        assert "Own benefit" in own_card
        assert "Inherited benefit" not in own_card
        assert "Inherited benefit" in inherited_card
        assert "Own benefit" not in inherited_card

    def test_inherited_orgs_listed_in_prose(self, organization_factory, plan_factory):
        """Several inherited orgs read as a comma separated list"""
        orgs = [organization_factory(name=name) for name in ("Alpha", "Beta", "Gamma")]

        html = self._render(
            upgrade_plan=plan_factory(),
            inherited_orgs=orgs,
            inherited_benefits=["Inherited benefit"],
        )

        assert ">Alpha</a>, " in html
        assert ">Beta</a> and " in html
        assert ">Gamma</a>:" in html

    def test_active_subscription_shows_price_and_renewal_date(
        self, organization_factory, plan_factory
    ):
        """An active subscription shows its price and next renewal date"""
        plan = plan_factory(name="Org Plan", annual=False, base_price=30)
        org = organization_factory(plans=[plan])
        subscription = org.subscription_items.get()
        # On the parent, where the period lives.  Setting it on the line put
        # an attribute on the instance handed to the template, so this test
        # passed by supplying the very field the page could not find.
        subscription.subscription.current_period_end = datetime.datetime(
            2026, 2, 15, 12, 0, tzinfo=datetime.timezone.utc
        )
        subscription.subscription.save()

        html = self._render(subscriptions=[subscription])

        assert "$30 per month" in html
        assert "Renews February 15, 2026" in html
        assert "Expires" not in html

    def test_annual_subscription_shows_per_year_price(
        self, organization_factory, plan_factory
    ):
        """An annual plan's price is shown per year rather than per month"""
        plan = plan_factory(name="Org Plan", annual=True, base_price=300)
        org = organization_factory(plans=[plan])

        html = self._render(subscriptions=list(org.subscription_items.all()))

        assert "$300 per year" in html

    def test_free_subscription_shows_free_instead_of_price(
        self, organization_factory, plan_factory
    ):
        """A free plan shows 'Free' rather than a $0 price"""
        plan = plan_factory(name="Org Plan", base_price=0, price_per_user=0)
        org = organization_factory(plans=[plan])

        html = self._render(subscriptions=list(org.subscription_items.all()))

        assert "Free" in html

    def test_cancelled_subscription_shows_price_and_expiration_date(
        self, organization_factory, plan_factory
    ):
        """A cancelled subscription shows its price and when it expires,
        instead of a renewal date"""
        plan = plan_factory(name="Org Plan", annual=False, base_price=30)
        org = organization_factory(plans=[plan])
        subscription = org.subscription_items.get()
        subscription.cancelled = True
        subscription.cancel_at = datetime.date(2026, 1, 15)
        subscription.current_period_end = datetime.datetime(
            2026, 1, 15, tzinfo=datetime.timezone.utc
        )
        subscription.save()

        html = self._render(subscriptions=[subscription])

        assert "$30 per month" in html
        assert "Ends January 15, 2026" in html
        assert "Renews" not in html

    def test_no_card_on_file_shows_fallback_text(
        self, organization_factory, plan_factory
    ):
        """When there is no card on file, the fallback text is shown"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])

        html = self._render(subscriptions=list(org.subscription_items.all()))

        assert "No card on file" in html

    def test_card_on_file_shows_brand_and_last4(
        self, organization_factory, plan_factory
    ):
        """When a card is on file, its brand and last 4 digits are shown"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])

        html = self._render(
            subscriptions=list(org.subscription_items.all()),
            card_brand="visa",
            card_last4="4242",
        )

        assert "visa" in html
        assert "4242" in html
        assert "No card on file" not in html

    def test_plan_name_links_to_plan_detail(self, organization_factory, plan_factory):
        """The plan name links to its detail page"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])

        html = self._render(subscriptions=list(org.subscription_items.all()))

        expected_url = reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
        assert f'href="{expected_url}"' in html


@pytest.mark.django_db
class TestOrganizationPaymentPlanInfo:
    """Rendering tests for organizations/plan_info.html

    Both values this block shows were reading attributes that do not exist -
    `organization.plan`, removed from the model long ago, and
    `subscription.update_on`, which was never on a subscription.  Django
    resolves a missing attribute to the empty string rather than raising, so
    the page cheerfully reported "Free" to paying customers and "ends on"
    with no date.  These pin both.
    """

    template = "organizations/plan_info.html"

    def _render(self, org, current=None):
        return render_to_string(
            self.template, {"organization": org, "current_subscription": current}
        )

    def test_subscribed_organization_shows_its_plans(self):
        item = SubscriptionItemFactory(plan=PlanFactory(name="Organization Tier"))
        org = item.subscription.organization

        html = self._render(org)

        assert "Organization Tier" in html
        assert "Free" not in html

    def test_several_plans_are_all_listed(self):
        first = SubscriptionItemFactory(plan=PlanFactory(name="Organization Tier"))
        SubscriptionItemFactory(
            subscription=first.subscription,
            plan=PlanFactory(name="MuckRock Request Pack"),
        )

        html = self._render(first.subscription.organization)

        assert "Organization Tier" in html
        assert "MuckRock Request Pack" in html

    def test_organization_with_no_subscription_shows_free(self, organization_factory):
        html = self._render(organization_factory())

        assert "Free" in html

    def test_cancelled_line_shows_the_date_it_ends(self):
        item = SubscriptionItemFactory(
            plan=PlanFactory(name="Organization Tier"),
            cancelled=True,
            cancel_at=date(2026, 9, 20),
        )

        html = self._render(item.subscription.organization, current=item)

        assert "09/20/2026" in html

    def test_no_banner_when_nothing_is_ending(self):
        item = SubscriptionItemFactory(plan=PlanFactory(name="Organization Tier"))

        html = self._render(item.subscription.organization, current=item)

        assert "ends on" not in html.lower()
