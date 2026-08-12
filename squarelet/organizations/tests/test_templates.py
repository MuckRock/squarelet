# Django
from django.template.loader import render_to_string

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import InvitationRole
from squarelet.organizations.tests.factories import InvitationFactory
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

    def test_own_benefits_listed_with_own_plans(
        self, organization_factory, plan_factory
    ):
        """Owned plans and the benefits they add up to render together"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])

        html = self._render(
            subscriptions=list(org.subscriptions.all()),
            subscription_benefits=["100 requests each month"],
        )

        assert "Org Plan" in html
        assert "Included benefits" in html
        assert "100 requests each month" in html

    def test_own_and_inherited_benefits_render_in_separate_cards(
        self, organization_factory, plan_factory
    ):
        """Benefits the org pays for are not listed alongside inherited ones"""
        plan = plan_factory(name="Org Plan")
        org = organization_factory(plans=[plan])
        parent = organization_factory(name="Parent Org")

        html = self._render(
            subscriptions=list(org.subscriptions.all()),
            subscription_benefits=["Own benefit"],
            inherited_orgs=[parent],
            inherited_benefits=["Inherited benefit"],
        )

        own_card, inherited_card = html.split('class="plan-card plan-card--inherited"')
        assert "Own benefit" in own_card
        assert "Inherited benefit" not in own_card
        assert "Inherited benefit" in inherited_card
        assert "Own benefit" not in inherited_card

    def test_inherited_orgs_listed_in_prose(self, organization_factory):
        """Several inherited orgs read as a comma separated list"""
        orgs = [organization_factory(name=name) for name in ("Alpha", "Beta", "Gamma")]

        html = self._render(
            inherited_orgs=orgs, inherited_benefits=["Inherited benefit"]
        )

        assert ">Alpha</a>, " in html
        assert ">Beta</a> and " in html
        assert ">Gamma</a>:" in html
