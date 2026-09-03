# Django
from django.template.loader import render_to_string

# Standard Library
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
