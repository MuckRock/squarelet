# pylint: disable=too-many-lines
# TODO: Refactor tests for each view file
# Django
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http.response import Http404
from django.test.utils import override_settings
from django.utils import timezone

# Standard Library
import json
from unittest.mock import MagicMock

# Third Party
import pytest
import stripe
from actstream.models import Action

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin

# Local
from .. import views
from ..models import OrganizationEmailDomain, ReceiptEmail

# pylint: disable=invalid-name,too-many-public-methods


@pytest.mark.django_db()
class TestDetail(ViewTestMixin):
    """Test the Organization Detail view"""

    view = views.Detail
    url = "/organizations/{slug}/"

    def test_get_anonymous(self, rf, organization_factory, user_factory):
        user = user_factory()
        admin = user_factory()
        organization = organization_factory(users=[user], admins=[admin])
        response = self.call_view(rf, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
        users = response.context_data["users"]
        assert len(users) == 1
        assert admin in users

    def test_get_member(self, rf, organization_factory, user_factory):
        user = user_factory()
        admin = user_factory()
        organization = organization_factory(users=[user], admins=[admin])
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
        users = response.context_data["users"]
        assert len(users) == 2
        assert admin in users and user in users
        assert not response.context_data["is_admin"]
        assert response.context_data["is_member"]
        assert "requested_invite" in response.context_data
        assert "invite_count" not in response.context_data

    def test_get_admin(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
        assert response.context_data["is_admin"]
        assert response.context_data["is_member"]
        assert "requested_invite" in response.context_data
        assert "pending_requests" in response.context_data
        # Verify pending_requests is a queryset
        assert response.context_data["pending_requests"].count() == 0

    def test_get_admin_with_pending_requests(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        """Test that pending_requests shows pending join requests"""
        admin = user_factory()
        organization = organization_factory(admins=[admin])
        # Create some pending join requests
        invitation_factory.create_batch(3, organization=organization, request=True)
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["is_admin"]
        # Verify pending_requests is a queryset with the correct count
        assert response.context_data["pending_requests"].count() == 3

    def test_get_staff_can_see_invite_count(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        """Test that staff members can see pending_requests even if not admin/member"""
        staff_user = user_factory(is_staff=True)
        organization = organization_factory()  # Staff not a member
        # Create some pending join requests
        invitation_factory.create_batch(2, organization=organization, request=True)
        response = self.call_view(rf, staff_user, slug=organization.slug)
        assert response.status_code == 200
        assert not response.context_data["is_admin"]
        assert not response.context_data["is_member"]
        # Staff should still see pending_requests
        assert "pending_requests" in response.context_data
        assert response.context_data["pending_requests"].count() == 2

    def test_member_counts_in_context(self, rf, organization_factory, user_factory):
        """Test that member_count and admin_count are in context"""
        admin = user_factory()
        members = user_factory.create_batch(3)
        organization = organization_factory(admins=[admin], users=members)
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        assert "member_count" in response.context_data
        assert "admin_count" in response.context_data
        # 1 admin + 3 members = 4 total users
        assert response.context_data["member_count"] == 4
        assert response.context_data["admin_count"] == 1

    def test_users_have_org_membership_list(
        self, rf, organization_factory, user_factory
    ):
        """Test that users in context have org_membership_list for template access"""
        admin = user_factory()
        member = user_factory()
        organization = organization_factory(admins=[admin], users=[member])
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        users = response.context_data["users"]
        # Check that each user has the org_membership_list attribute
        for user in users:
            assert hasattr(user, "org_membership_list")
            assert len(user.org_membership_list) > 0
            # Verify the membership has the admin attribute
            membership = user.org_membership_list[0]
            assert hasattr(membership, "admin")
            # The admin user should have admin=True
            if user == admin:
                assert membership.admin is True
            # The regular member should have admin=False
            elif user == member:
                assert membership.admin is False
        # Verify the current user (admin) is first in the list
        assert users[0] == admin

    def test_verification_context_for_unverified_org_admin(
        self, rf, organization_factory, user_factory
    ):
        """Test verification context for admin of unverified org"""
        admin = user_factory()
        organization = organization_factory(admins=[admin], verified_journalist=False)
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["show_verification_request"] is True

    def test_verification_context_for_verified_org_admin(
        self, rf, organization_factory, user_factory
    ):
        """Test verification context for admin of verified org"""
        admin = user_factory()
        organization = organization_factory(admins=[admin], verified_journalist=True)
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["show_verification_request"] is False

    def test_verification_context_for_member(
        self, rf, organization_factory, user_factory
    ):
        """Test that members don't see verification request prompt"""
        member = user_factory()
        organization = organization_factory(users=[member], verified_journalist=False)
        response = self.call_view(rf, member, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["show_verification_request"] is False

    def test_security_settings_context_for_admin(
        self, rf, organization_factory, user_factory
    ):
        """Test that admins see security settings in context"""
        admin = user_factory()
        organization = organization_factory(admins=[admin], allow_auto_join=True)
        response = self.call_view(rf, admin, slug=organization.slug)
        assert response.status_code == 200
        assert "security_settings" in response.context_data
        assert response.context_data["security_settings"]["allow_auto_join"] is True
        assert "has_email_domains" in response.context_data["security_settings"]

    def test_security_settings_context_for_member(
        self, rf, organization_factory, user_factory
    ):
        """Test that members don't see security settings"""
        member = user_factory()
        organization = organization_factory(users=[member])
        response = self.call_view(rf, member, slug=organization.slug)
        assert response.status_code == 200
        assert "security_settings" not in response.context_data

    def test_security_settings_context_for_staff(
        self, rf, organization_factory, user_factory
    ):
        """Test that staff see security settings even if not member"""
        staff_user = user_factory(is_staff=True)
        organization = organization_factory(allow_auto_join=False)
        response = self.call_view(rf, staff_user, slug=organization.slug)
        assert response.status_code == 200
        assert "security_settings" in response.context_data
        assert response.context_data["security_settings"]["allow_auto_join"] is False

    def test_get_individual(self, rf, individual_organization_factory):
        """Individual organizations should not have a detail page"""
        organization = individual_organization_factory()
        with pytest.raises(Http404):
            self.call_view(rf, slug=organization.slug)

    def test_get_member_private(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(users=[user], private=True)
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
        assert not response.context_data["is_admin"]
        assert response.context_data["is_member"]
        assert "requested_invite" in response.context_data
        assert "invite_count" not in response.context_data

    def test_get_non_member_private(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(private=True)
        with pytest.raises(Http404):
            self.call_view(rf, user, slug=organization.slug)

    def test_post_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, data={"action": "join"}, slug=organization.slug)
        assert response.status_code == 302

    def test_post_join(self, rf, mailoutbox, organization_factory, user_factory):
        admin, joiner = user_factory.create_batch(2)
        organization = organization_factory(admins=[admin])
        response = self.call_view(
            rf, joiner, {"action": "join"}, slug=organization.slug
        )
        assert response.status_code == 302
        assert organization.invitations.filter(
            email=joiner.email, user=joiner, request=True
        ).exists()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == f"{joiner} has requested to join {organization}"
        assert mail.to == [admin.email]

    def test_post_member_join(self, rf, mailoutbox, organization_factory, user_factory):
        admin, joiner = user_factory.create_batch(2)
        organization = organization_factory(admins=[admin], users=[joiner])
        response = self.call_view(
            rf, joiner, {"action": "join"}, slug=organization.slug
        )
        assert response.status_code == 302
        assert not organization.invitations.filter(
            email=joiner.email, user=joiner, request=True
        ).exists()
        assert not mailoutbox

    def test_post_member_leave(self, rf, organization_factory, user_factory):
        admin, leaver = user_factory.create_batch(2)
        organization = organization_factory(admins=[admin], users=[leaver])
        response = self.call_view(
            rf, leaver, {"action": "leave"}, slug=organization.slug
        )
        assert response.status_code == 302
        assert not organization.has_member(leaver)

    def test_post_staff_remove_user(self, rf, organization_factory, user_factory):
        """Staff member should be able to remove a user from an organization"""
        staff_member = user_factory(is_staff=True)
        target_user = user_factory()
        organization = organization_factory(users=[target_user])

        response = self.call_view(
            rf,
            staff_member,
            {"action": "leave", "userid": target_user.pk},
            slug=organization.slug,
        )
        assert response.status_code == 302
        assert not organization.has_member(target_user)
        # Ensure staff member is not affected
        assert not organization.has_member(staff_member)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="removed member from organization",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == target_user
        assert action.target == organization
        assert action.public is False

    def test_post_staff_remove_admin(self, rf, organization_factory, user_factory):
        """Staff member should be able to remove an admin from an organization"""
        staff_member = user_factory(is_staff=True)
        target_admin = user_factory()
        organization = organization_factory(admins=[target_admin])

        response = self.call_view(
            rf,
            staff_member,
            {"action": "leave", "userid": target_admin.pk},
            slug=organization.slug,
        )
        assert response.status_code == 302
        assert not organization.has_member(target_admin)
        assert not organization.has_admin(target_admin)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="removed member from organization",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == target_admin
        assert action.target == organization
        assert action.public is False

    def test_post_staff_remove_other_staff(
        self, rf, organization_factory, user_factory
    ):
        """Staff member should be able to remove another staff member from an org"""
        staff_member1 = user_factory(is_staff=True)
        staff_member2 = user_factory(is_staff=True)
        organization = organization_factory(users=[staff_member2])

        response = self.call_view(
            rf,
            staff_member1,
            {"action": "leave", "userid": staff_member2.pk},
            slug=organization.slug,
        )
        assert response.status_code == 302
        assert not organization.has_member(staff_member2)

    def test_post_non_staff_cannot_remove_other_user(
        self, rf, organization_factory, user_factory
    ):
        """Non-staff member should not be able to remove another user"""
        regular_user = user_factory()
        target_user = user_factory()
        organization = organization_factory(users=[regular_user, target_user])

        response = self.call_view(
            rf,
            regular_user,
            {"action": "leave", "userid": target_user.pk},
            slug=organization.slug,
        )
        assert response.status_code == 302
        # Both users should still be members since non-staff can't remove others
        assert organization.has_member(target_user)
        assert organization.has_member(regular_user)
        self.assert_message(
            messages.ERROR, "You do not have permission to remove other users"
        )

        # Verify no activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(regular_user.pk),
            verb="removed member from organization",
        ).first()
        assert action is None

    def test_post_staff_remove_themselves_with_userid(
        self, rf, organization_factory, user_factory
    ):
        """Staff member should be able to remove themselves using userid parameter"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory(users=[staff_member])

        response = self.call_view(
            rf,
            staff_member,
            {"action": "leave", "userid": staff_member.pk},
            slug=organization.slug,
        )
        assert response.status_code == 302
        assert not organization.has_member(staff_member)

    def test_post_staff_remove_nonexistent_user(
        self, rf, organization_factory, user_factory
    ):
        """Staff trying to remove a non-existent user should handle gracefully"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()

        # Try to remove a user with an ID that doesn't exist
        response = self.call_view(
            rf,
            staff_member,
            {"action": "leave", "userid": 99999},
            slug=organization.slug,
        )
        # Should still redirect but show an error message
        assert response.status_code == 302


@pytest.mark.django_db()
def test_list(rf, organization_factory):
    organization_factory.create_batch(5)
    request = rf.get("/organizations/")
    request.user = AnonymousUser()
    response = views.List.as_view()(request)
    assert response.status_code == 200
    assert len(response.context_data["organization_list"]) == 5


@pytest.mark.django_db()
class TestUpdate(ViewTestMixin):
    """Test the Organization Update view (profile updates)"""

    view = views.Update
    url = "/organizations/{slug}/update/"

    def test_staff_update_profile_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff updating organization profile should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()

        response = self.call_view(
            rf,
            staff_member,
            {"about": "New about text", "private": "on"},
            slug=organization.slug,
        )
        assert response.status_code == 302

        # Verify data was actually updated
        organization.refresh_from_db()
        assert organization.about == "New about text"
        assert organization.private is True

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="updated the profile",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.target == organization
        assert action.public is False
        assert "about" in action.description
        assert "private" in action.description

    def test_non_staff_update_profile_does_not_create_action(
        self, rf, organization_factory, user_factory
    ):
        """Non-staff updating organization profile should NOT create action"""
        regular_admin = user_factory(is_staff=False)
        organization = organization_factory(admins=[regular_admin])

        response = self.call_view(
            rf,
            regular_admin,
            {"about": "New about text", "private": "on"},
            slug=organization.slug,
        )
        assert response.status_code == 302

        # Verify no activity stream action was created
        action = Action.objects.filter(
            verb="updated the profile",
        ).first()
        assert action is None


@pytest.mark.django_db()
class TestRequestProfileChange(ViewTestMixin):
    """Test RequestProfileChange view for submitting profile change requests"""

    view = views.RequestProfileChange
    url = "/organizations/{slug}/request-profile-change/"

    def test_staff_submit_profile_change_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff submitting profile change should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()

        response = self.call_view(
            rf,
            staff_member,
            {"name": "New Organization Name", "explanation": "Testing"},
            slug=organization.slug,
        )
        assert response.status_code == 302

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="submitted profile change request",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.target == organization
        assert action.public is False
        assert "name" in action.description

    def test_non_staff_submit_profile_change_does_not_create_action(
        self, rf, organization_factory, user_factory
    ):
        """Non-staff submitting profile change should NOT create action"""
        regular_admin = user_factory(is_staff=False)
        organization = organization_factory(admins=[regular_admin])

        response = self.call_view(
            rf,
            regular_admin,
            {"name": "New Organization Name", "explanation": "Testing changes"},
            slug=organization.slug,
        )
        assert response.status_code == 302

        # Verify no activity stream action was created
        action = Action.objects.filter(
            verb="submitted profile change request",
        ).first()
        assert action is None


@pytest.mark.django_db()
class TestReviewProfileChange(ViewTestMixin):
    """Test ReviewProfileChange view for staff accepting/rejecting changes"""

    view = views.ReviewProfileChange
    url = "/organizations/{slug}/review-profile-change/{pk}/"

    def test_staff_accept_profile_change_creates_action(
        self, rf, organization_factory, user_factory, profile_change_request_factory
    ):
        """Staff accepting profile change should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()
        profile_change = profile_change_request_factory(
            organization=organization,
            status="pending",
            name="New Organization Name",
        )

        response = self.call_view(
            rf,
            staff_member,
            {"action": "accept"},
            slug=organization.slug,
            pk=profile_change.pk,
        )
        assert response.status_code == 302

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="accepted profile change request",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == profile_change
        assert action.target == organization
        assert action.public is False

    def test_staff_reject_profile_change_creates_action(
        self, rf, organization_factory, user_factory, profile_change_request_factory
    ):
        """Staff rejecting profile change should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()
        profile_change = profile_change_request_factory(
            organization=organization,
            status="pending",
            name="New Organization Name",
        )

        response = self.call_view(
            rf,
            staff_member,
            {"action": "reject"},
            slug=organization.slug,
            pk=profile_change.pk,
        )
        assert response.status_code == 302

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="rejected profile change request",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == profile_change
        assert action.target == organization
        assert action.public is False

    def test_non_staff_cannot_review_profile_change(
        self, rf, organization_factory, user_factory, profile_change_request_factory
    ):
        """Non-staff user should not be able to review and should not create action"""
        regular_user = user_factory(is_staff=False)
        organization = organization_factory()
        profile_change = profile_change_request_factory(
            organization=organization,
            status="pending",
            name="New Organization Name",
        )

        response = self.call_view(
            rf,
            regular_user,
            {"action": "accept"},
            slug=organization.slug,
            pk=profile_change.pk,
        )
        assert response.status_code == 302

        # Verify no activity stream action was created
        action = Action.objects.filter(
            verb__in=[
                "accepted profile change request",
                "rejected profile change request",
            ],
        ).first()
        assert action is None


@pytest.mark.django_db()
class TestAutocomplete:
    def call_view(self, rf, data):
        request = rf.get("/organizations/autocomplete/", data)
        request.user = AnonymousUser()
        return views.autocomplete(request)

    def test_simple(self, rf, organization_factory):
        orgs = sorted(organization_factory.create_batch(5), key=lambda x: x.slug)
        response = self.call_view(rf, {})
        assert response.status_code == 200
        content = json.loads(response.content)
        assert content["data"] == [
            {"name": o.name, "slug": o.slug, "avatar": o.avatar_url} for o in orgs
        ]

    def test_query(self, rf, organization_factory):
        organization_factory.create_batch(5)
        org = organization_factory.create(name="example")
        response = self.call_view(rf, {"q": "exam"})
        assert response.status_code == 200
        content = json.loads(response.content)
        assert content["data"] == [
            {"name": org.name, "slug": org.slug, "avatar": org.avatar_url}
        ]

    def test_page(self, rf, organization_factory):
        organization_factory.create_batch(101)
        response = self.call_view(rf, {"page": "2"})
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["data"]) == 1


@pytest.mark.django_db()
class TestUpdateSubscription(ViewTestMixin):
    """Test the Organization Update Subscription view"""

    view = views.UpdateSubscription
    url = "/organizations/{slug}/payment/"

    def test_get_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, slug=organization.slug)
        assert response.status_code == 302

    def test_get_admin(self, rf, organization_factory, user_factory, mocker):
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        user = user_factory()
        organization = organization_factory(admins=[user])
        ReceiptEmail.objects.create(
            organization=organization, email="receipts@example.com", failed=False
        )
        failed_email = ReceiptEmail.objects.create(
            organization=organization, email="failed@example.com", failed=True
        )
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["failed_receipt_emails"][0] == failed_email
        initial = response.context_data["form"].initial
        assert initial["plan"] == organization.plan
        assert initial["max_users"] == organization.max_users
        assert len(initial["receipt_emails"].split("\n")) == 2

    def test_post_admin(self, rf, organization_factory, user_factory, mocker):
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.set_subscription"
        )
        user = user_factory()
        organization = organization_factory(admins=[user])
        data = {
            "stripe_token": "token",
            "plan": "",
            "max_users": 6,
            "receipt_emails": "receipt1@example.com\nreceipt2@example.com",
            "stripe_pk": "key",
        }
        response = self.call_view(rf, user, data, slug=organization.slug)
        assert response.status_code == 302
        assert mocked.called_with(
            token=data["stripe_token"],
            plan=organization.plan,
            max_user=data["max_users"],
        )
        assert set(e.email for e in organization.receipt_emails.all()) == set(
            data["receipt_emails"].split("\n")
        )

    def test_post_admin_stripe_error(
        self, rf, organization_factory, user_factory, mocker
    ):
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.set_subscription"
        )
        mocked.side_effect = stripe.error.StripeError("Error message")
        user = user_factory()
        organization = organization_factory(admins=[user])
        data = {
            "stripe_token": "token",
            "plan": "",
            "max_users": 6,
            "receipt_emails": "receipt1@example.com\nreceipt2@example.com",
            "stripe_pk": "key",
        }
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(
            messages.ERROR,
            "Payment error: We're unable to process your payment at this time. "
            "Please try again later or "
            '<a href="mailto:info@muckrock.com?subject='
            "Payment%20Processing%20Error"
            "&body=Error%20Type%3A%20StripeError%0A"
            "Error%20Message%3A%20Error%20message"
            '">contact support</a> for assistance.',
        )

    def test_post_staff_updates_subscription_creates_action(
        self, rf, organization_factory, user_factory, mocker
    ):
        """Staff updating subscription should create activity stream action"""
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        mocker.patch("squarelet.organizations.models.Organization.set_subscription")
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()
        data = {
            "stripe_token": "token",
            "plan": "",
            "max_users": 10,
            "receipt_emails": "receipt@example.com",
            "stripe_pk": "key",
        }
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="updated organization subscription",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.target == organization
        assert action.public is False

    def test_post_non_staff_admin_no_action_created(
        self, rf, organization_factory, user_factory, mocker
    ):
        """Non-staff admin updating subscription should not create action"""
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        mocker.patch("squarelet.organizations.models.Organization.set_subscription")
        regular_admin = user_factory(is_staff=False)
        organization = organization_factory(admins=[regular_admin])
        data = {
            "stripe_token": "token",
            "plan": "",
            "max_users": 10,
            "receipt_emails": "receipt@example.com",
            "stripe_pk": "key",
        }
        self.call_view(rf, regular_admin, data, slug=organization.slug)

        # Verify no activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(regular_admin.pk),
            verb="updated organization subscription",
        ).first()
        assert action is None


@pytest.mark.django_db()
class TestCreate(ViewTestMixin):
    """Test the Organization Create view"""

    view = views.Create
    url = "/organizations/~create/"

    def test(self, rf, user_factory):
        user = user_factory()
        self.call_view(rf, user, {"name": "test"})
        organization = user.organizations.get(individual=False)
        assert organization.plan is None
        assert organization.has_admin(user)
        assert user.email in organization.receipt_emails.values_list("email", flat=True)


@pytest.mark.django_db()
class TestManageMembers(ViewTestMixin):  # pylint: disable=too-many-public-methods
    """Test the ManageMembers Create view"""

    view = views.ManageMembers
    url = "/organizations/{slug}/manage-members/"

    def test_get(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["admin"] == user

    def test_add_member_good(self, rf, mailoutbox, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        email = "invite@example.com"
        data = {"action": "addmember", "emails": email}
        self.call_view(rf, user, data, slug=organization.slug)
        assert organization.invitations.filter(email=email).exists()
        mail = mailoutbox[0]
        assert mail.subject == f"Invitation to join {organization.name}"
        assert mail.to == [email]
        self.assert_message(messages.SUCCESS, "1 invitation sent")

    def test_add_member_bad_email(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        email = "not an email"
        data = {"action": "addmember", "emails": email}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "Enter a valid email address.")

    def test_add_member_good_user_limit(self, rf, organization_factory, user_factory):
        """Test having more users than max_users"""
        user = user_factory()
        members = user_factory.create_batch(4)
        organization = organization_factory(admins=[user], users=members, max_users=5)
        email = "invite@example.com"
        data = {"action": "addmember", "emails": email}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.SUCCESS, "1 invitation sent")
        organization.refresh_from_db()
        assert organization.max_users == 5

    def test_revoke_invite(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        invitation = invitation_factory(organization=organization)
        data = {"action": "revokeinvite", "inviteid": invitation.pk}
        self.call_view(rf, user, data, slug=organization.slug)
        invitation.refresh_from_db()
        assert invitation.rejected_at is not None
        self.assert_message(
            messages.SUCCESS, f"Invitation to {invitation.email} revoked"
        )

    def test_accept_invite(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        invitation = invitation_factory(organization=organization, user=user_factory())
        data = {"action": "acceptinvite", "inviteid": invitation.pk}
        self.call_view(rf, user, data, slug=organization.slug)
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None
        self.assert_message(
            messages.SUCCESS, f"Invitation from {invitation.email} accepted"
        )

    def test_reject_invite(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        invitation = invitation_factory(organization=organization)
        data = {"action": "rejectinvite", "inviteid": invitation.pk}
        self.call_view(rf, user, data, slug=organization.slug)
        invitation.refresh_from_db()
        assert invitation.rejected_at is not None
        self.assert_message(
            messages.SUCCESS, f"Invitation from {invitation.email} rejected"
        )

    def test_revoke_invite_missing(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        data = {"action": "revokeinvite", "inviteid": 1}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "An unexpected error occurred")

    def test_revoke_invite_closed(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        now = timezone.now()
        invitation = invitation_factory(organization=organization, rejected_at=now)
        data = {"action": "revokeinvite", "inviteid": invitation.pk}
        self.call_view(rf, user, data, slug=organization.slug)
        invitation.refresh_from_db()
        assert invitation.rejected_at == now
        self.assert_message(messages.ERROR, "An unexpected error occurred")

    def test_make_admin(self, rf, organization_factory, user_factory):
        admin = user_factory()
        member = user_factory()
        organization = organization_factory(admins=[admin], users=[member])
        data = {"action": "makeadmin", "userid": member.pk, "admin": "true"}
        self.call_view(rf, admin, data, slug=organization.slug)
        assert organization.has_admin(member)
        self.assert_message(messages.SUCCESS, f"{member.username} promoted to admin")

    def test_remove_admin(self, rf, organization_factory, user_factory):
        admins = user_factory.create_batch(2)
        organization = organization_factory(admins=admins)
        data = {"action": "makeadmin", "userid": admins[1].pk, "admin": "false"}
        self.call_view(rf, admins[0], data, slug=organization.slug)
        assert not organization.has_admin(admins[1])
        self.assert_message(messages.SUCCESS, f"{admins[1].username} demoted to member")

    def test_make_admin_bad_bool(self, rf, organization_factory, user_factory):
        admin = user_factory()
        member = user_factory()
        organization = organization_factory(admins=[admin], users=[member])
        data = {"action": "makeadmin", "userid": member.pk, "admin": "foo"}
        self.call_view(rf, admin, data, slug=organization.slug)
        assert not organization.has_admin(member)
        self.assert_message(messages.ERROR, "An unexpected error occurred")

    def test_make_admin_bad_member(self, rf, organization_factory, user_factory):
        admin = user_factory()
        user = user_factory()
        organization = organization_factory(admins=[admin])
        data = {"action": "makeadmin", "userid": user.pk, "admin": "true"}
        self.call_view(rf, admin, data, slug=organization.slug)
        assert not organization.has_admin(user)
        self.assert_message(messages.ERROR, "An unexpected error occurred")

    def test_remove_user(self, rf, organization_factory, user_factory):
        admin = user_factory()
        member = user_factory()
        organization = organization_factory(admins=[admin], users=[member])
        data = {"action": "removeuser", "userid": member.pk}
        self.call_view(rf, admin, data, slug=organization.slug)
        assert not organization.has_member(member)
        self.assert_message(messages.SUCCESS, f"{member.username} removed")

    def test_bad_action(self, rf, organization_factory, user_factory):
        admin = user_factory()
        organization = organization_factory(admins=[admin])
        data = {"action": "fakeaction"}
        self.call_view(rf, admin, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "An unexpected error occurred")

    def test_staff_make_admin_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff promoting user to admin should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        member = user_factory()
        organization = organization_factory(users=[member])
        data = {"action": "makeadmin", "userid": member.pk, "admin": "true"}
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="promoted member to admin",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == member
        assert action.target == organization
        assert action.public is False

    def test_staff_demote_admin_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff demoting admin to member should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        admin_user = user_factory()
        organization = organization_factory(admins=[admin_user])
        data = {"action": "makeadmin", "userid": admin_user.pk, "admin": "false"}
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="demoted admin to member",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == admin_user
        assert action.target == organization
        assert action.public is False

    def test_non_staff_admin_makeadmin_no_action(
        self, rf, organization_factory, user_factory
    ):
        """Non-staff admin promoting user should not create action"""
        regular_admin = user_factory(is_staff=False)
        member = user_factory()
        organization = organization_factory(admins=[regular_admin], users=[member])
        data = {"action": "makeadmin", "userid": member.pk, "admin": "true"}
        self.call_view(rf, regular_admin, data, slug=organization.slug)

        # Verify no activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(regular_admin.pk),
            verb="promoted member to admin",
        ).first()
        assert action is None

    def test_staff_remove_user_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff removing user should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        member = user_factory()
        organization = organization_factory(users=[member])
        data = {"action": "removeuser", "userid": member.pk}
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="removed member from organization",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == member
        assert action.target == organization
        assert action.public is False

    def test_staff_add_member_creates_action(
        self, rf, organization_factory, user_factory
    ):
        """Staff sending invitation should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()
        email = "invite@example.com"
        data = {"action": "addmember", "emails": email}
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="sent organization invitation",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.target == organization
        assert action.public is False

    def test_staff_revoke_invite_creates_action(
        self, rf, organization_factory, user_factory, invitation_factory
    ):
        """Staff revoking invitation should create activity stream action"""
        staff_member = user_factory(is_staff=True)
        organization = organization_factory()
        invitation = invitation_factory(organization=organization)
        data = {"action": "revokeinvite", "inviteid": invitation.pk}
        self.call_view(rf, staff_member, data, slug=organization.slug)

        # Verify activity stream action was created
        action = Action.objects.filter(
            actor_object_id=str(staff_member.pk),
            verb="revoked organization invitation",
        ).first()
        assert action is not None
        assert action.actor == staff_member
        assert action.action_object == invitation
        assert action.target == organization
        assert action.public is False


@pytest.mark.django_db()
class TestInvitationAccept(ViewTestMixin):
    """Test the Organization InvitationAccept view"""

    view = views.InvitationAccept
    url = "/organizations/{uuid}/invitation/"

    def test_accept(self, rf, invitation_factory, user_factory):
        invitation = invitation_factory()
        user = user_factory()
        self.call_view(rf, user, {"action": "accept"}, uuid=invitation.uuid)
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None
        assert invitation.organization.has_member(user)

    def test_reject(self, rf, invitation_factory, user_factory):
        invitation = invitation_factory()
        user = user_factory()
        self.call_view(rf, user, {"action": "reject"}, uuid=invitation.uuid)
        invitation.refresh_from_db()
        assert invitation.rejected_at is not None
        assert not invitation.organization.has_member(user)

    def test_other(self, rf, invitation_factory, user_factory):
        invitation = invitation_factory()
        user = user_factory()
        self.call_view(rf, user, {"action": "invalid"}, uuid=invitation.uuid)
        invitation.refresh_from_db()
        assert invitation.accepted_at is None
        assert invitation.rejected_at is None

    def test_accept_with_referer(self, rf, invitation_factory, user_factory):
        """Test that accept redirects to HTTP_REFERER when present"""
        invitation = invitation_factory()
        user = user_factory()

        # Create request with HTTP_REFERER
        url = self.url.format(uuid=invitation.uuid)
        request = rf.post(url, {"action": "accept"})
        request.user = user
        # pylint: disable=protected-access
        request._messages = MagicMock()
        request.session = MagicMock()
        request.META["HTTP_REFERER"] = "/some/previous/page/"

        response = self.view.as_view()(request, uuid=invitation.uuid)

        assert response.status_code == 302
        assert response.url == "/some/previous/page/"

    def test_reject_with_referer(self, rf, invitation_factory, user_factory):
        """Test that reject redirects to HTTP_REFERER when present"""
        invitation = invitation_factory()
        user = user_factory()

        # Create request with HTTP_REFERER
        url = self.url.format(uuid=invitation.uuid)
        request = rf.post(url, {"action": "reject"})
        request.user = user
        # pylint: disable=protected-access
        request._messages = MagicMock()
        request.session = MagicMock()
        request.META["HTTP_REFERER"] = "/another/page/"

        response = self.view.as_view()(request, uuid=invitation.uuid)

        assert response.status_code == 302
        assert response.url == "/another/page/"

    def test_accept_without_referer(self, rf, invitation_factory, user_factory):
        """Test that accept falls back to default redirect when no HTTP_REFERER"""
        invitation = invitation_factory()
        user = user_factory()

        response = self.call_view(rf, user, {"action": "accept"}, uuid=invitation.uuid)

        assert response.status_code == 302
        # Should redirect to the organization (default fallback)
        assert f"/organizations/{invitation.organization.slug}/" in response.url

    def test_reject_without_referer(self, rf, invitation_factory, user_factory):
        """Test that reject falls back to default redirect when no HTTP_REFERER"""
        invitation = invitation_factory()
        user = user_factory()

        response = self.call_view(rf, user, {"action": "reject"}, uuid=invitation.uuid)

        assert response.status_code == 302
        # Should redirect to the user (default fallback)
        assert f"/users/{user.username}/" in response.url


@pytest.mark.django_db()
class TestChargeDetail(ViewTestMixin):
    """Test the Organization Receipts view"""

    view = views.ChargeDetail
    url = "/organizations/~charges/{pk}/"

    def test_get_member(self, rf, organization_factory, user_factory, charge_factory):
        user = user_factory()
        organization = organization_factory(users=[user])
        charge = charge_factory(organization=organization)
        with pytest.raises(PermissionDenied):
            self.call_view(rf, user, pk=charge.pk)

    def test_get_admin(self, rf, organization_factory, user_factory, charge_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        charge = charge_factory(organization=organization)
        response = self.call_view(rf, user, pk=charge.pk)
        assert response.status_code == 200
        assert response.context_data["subject"] == "Receipt"


class TestStripeWebhook:
    def call_view(self, rf, data):
        request = rf.post(
            "/organizations/~stripe_webhook/",
            json.dumps(data),
            content_type="application/json",
        )
        return views.stripe_webhook(request)

    def test_simple(self, rf):
        """Succesful request"""
        event = {"type": "test"}
        response = self.call_view(rf, event)
        assert response.status_code == 200

    def test_get(self, rf):
        """GET requests should fail"""
        request = rf.get("/organizations/~stripe_webhook/")
        response = views.stripe_webhook(request)
        assert response.status_code == 405

    def test_bad_json(self, rf):
        """Malformed JSON should fail"""
        request = rf.post(
            "/organizations/~stripe_webhook/",
            "{'malformed json'",
            content_type="application/json",
        )
        response = views.stripe_webhook(request)
        assert response.status_code == 400

    def test_missing_key(self, rf):
        """Missing event type should fail"""
        event = {"foo": "bar"}
        response = self.call_view(rf, event)
        assert response.status_code == 400

    @override_settings(STRIPE_WEBHOOK_SECRET=["123"])
    def test_signature_verification(self, rf):
        """Signature verification error should fail"""
        event = {"type": "test"}
        response = self.call_view(rf, event)
        assert response.status_code == 400


@pytest.mark.django_db()
class TestManageDomains(ViewTestMixin):
    """Test the ManageDomains View"""

    view = views.ManageDomains
    url = "/organizations/{slug}/manage-domains/"

    def test_get(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["admin"] == user

    def test_add_domain_good(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        domain = "newdomain.com"
        data = {"action": "adddomain", "domain": domain}
        self.call_view(rf, user, data, slug=organization.slug)
        assert OrganizationEmailDomain.objects.filter(
            organization=organization, domain=domain
        ).exists()
        self.assert_message(
            messages.SUCCESS, f"The domain {domain} was added successfully."
        )

    def test_add_domain_invalid_format(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        domain = "invalid_domain"
        data = {"action": "adddomain", "domain": domain}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(
            messages.ERROR, "Invalid domain format. Please enter a valid domain."
        )

    def test_add_domain_blacklisted(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        domain = "gmail.com"
        data = {"action": "adddomain", "domain": domain}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, f"The domain {domain} is not allowed.")

    def test_add_domain_duplicate(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        domain = "existingdomain.com"
        # Adding the domain once
        OrganizationEmailDomain.objects.create(organization=organization, domain=domain)
        data = {"action": "adddomain", "domain": domain}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, f"The domain {domain} is already added.")

    def test_remove_domain(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        domain = "removabledomain.com"
        # Adding the domain first
        OrganizationEmailDomain.objects.create(organization=organization, domain=domain)
        data = {"action": "removedomain", "domain": domain}
        self.call_view(rf, user, data, slug=organization.slug)
        assert not OrganizationEmailDomain.objects.filter(
            organization=organization, domain=domain
        ).exists()
        self.assert_message(
            messages.SUCCESS, f"The domain {domain} was removed successfully."
        )

    def test_bad_action(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=True)
        data = {"action": "fakeaction"}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "An unexpected error occurred.")

    def test_add_domain_non_admin(self, rf, organization_factory, user_factory):
        # Create a regular user and a non-admin organization
        user = user_factory()
        organization = organization_factory(admins=[])  # No admins
        data = {"action": "adddomain", "domain": "example.com"}

        # Call the view with the non-admin user and ensure PermissionDenied is raised
        with pytest.raises(PermissionDenied):
            self.call_view(rf, user, data, slug=organization.slug)

    def test_add_domain_non_verified_org(self, rf, organization_factory, user_factory):
        # Create a user and a non-verified organization
        user = user_factory()
        organization = organization_factory(admins=[user], verified_journalist=False)
        data = {"action": "adddomain", "domain": "example.com"}

        # Call the view with the user and ensure PermissionDenied is raised
        with pytest.raises(PermissionDenied):
            self.call_view(rf, user, data, slug=organization.slug)
