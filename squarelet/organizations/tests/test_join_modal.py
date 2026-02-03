# Django
from django.urls import reverse
from django.utils import timezone

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin

# Local
from .. import views

# pylint: disable=invalid-name


@pytest.mark.django_db()
class TestJoinRequestModal(ViewTestMixin):
    """Test the join request modal and confirmation page"""

    def test_modal_appears_on_detail_page(self, rf, organization_factory, user_factory):
        """Modal HTML should be present on organization detail page"""
        user = user_factory()
        organization = organization_factory()

        self.url = "/organizations/{slug}/"
        self.view = views.Detail
        response = self.call_view(rf, user, slug=organization.slug)
        response.render()

        assert response.status_code == 200
        assert b"join-request-modal-backdrop" in response.content
        assert b"Request to join organization?" in response.content

    def test_join_button_has_correct_attributes(
        self, rf, organization_factory, user_factory
    ):
        """Join button should have correct id and href for progressive enhancement"""
        user = user_factory()
        organization = organization_factory()

        self.url = "/organizations/{slug}/"
        self.view = views.Detail
        response = self.call_view(rf, user, slug=organization.slug)
        response.render()

        assert response.status_code == 200
        assert b'id="join-org-button"' in response.content
        confirm_url = reverse("organizations:join-confirm", args=[organization.slug])
        assert confirm_url.encode() in response.content

    def test_confirmation_page_shows_educational_content(
        self, rf, organization_factory, user_factory
    ):
        """Confirmation page should show the same educational content as modal"""
        user = user_factory()
        organization = organization_factory()

        self.url = "/organizations/{slug}/join-confirm/"
        self.view = views.JoinRequestConfirm
        response = self.call_view(rf, user, slug=organization.slug)
        response.render()

        assert response.status_code == 200
        # Check for key educational messages
        assert b"collaboration between colleagues" in response.content
        assert b"contact the organization" in response.content
        assert b"official contact channels" in response.content

    def test_confirmation_page_submits_with_confirmed_flag(
        self, rf, mailoutbox, organization_factory, user_factory
    ):
        """Submitting from confirmation page should include confirmed=true"""
        user = user_factory()
        admin = user_factory()
        organization = organization_factory(admins=[admin])

        # The form posts to the detail view, not the join-confirm view
        self.url = "/organizations/{slug}/"
        self.view = views.Detail
        response = self.call_view(
            rf,
            user,
            data={"action": "join"},
            slug=organization.slug,
        )

        # Should redirect back to org detail
        assert response.status_code == 302
        # Should create invitation
        assert organization.invitations.filter(
            email=user.email, user=user, request=True
        ).exists()
        # Should send email
        assert len(mailoutbox) == 1

    def test_modal_not_shown_for_members(self, rf, organization_factory, user_factory):
        """Modal should not appear for existing members"""
        user = user_factory()
        organization = organization_factory(users=[user])

        self.url = "/organizations/{slug}/"
        self.view = views.Detail
        response = self.call_view(rf, user, slug=organization.slug)
        response.render()

        assert response.status_code == 200
        # Join button should not be present for members
        assert b'id="join-org-button"' not in response.content

    def test_modal_not_shown_for_rejected_users(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        """Modal should not appear for users with rejected requests"""
        user = user_factory()
        organization = organization_factory()
        invitation_factory(
            organization=organization,
            user=user,
            request=True,
            rejected_at=timezone.now(),
        )

        self.url = "/organizations/{slug}/"
        self.view = views.Detail
        response = self.call_view(rf, user, slug=organization.slug)
        response.render()

        assert response.status_code == 200
        # Join button should not be present
        assert b'id="join-org-button"' not in response.content
        # Should show rejection message instead
        assert (
            b"Your request to join this organization was rejected" in response.content
        )
