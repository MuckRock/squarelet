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
