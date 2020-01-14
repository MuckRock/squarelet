# Django
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http.response import Http404
from django.test.utils import override_settings
from django.utils import timezone

# Standard Library
import json

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin

# Local
from .. import views
from ..models import ReceiptEmail

# pylint: disable=invalid-name


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
        assert "invite_count" in response.context_data

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


@pytest.mark.django_db()
def test_list(rf, organization_factory):
    organization_factory.create_batch(5)
    request = rf.get(f"/organizations/")
    request.user = AnonymousUser()
    response = views.List.as_view()(request)
    assert response.status_code == 200
    assert len(response.context_data["organization_list"]) == 5


@pytest.mark.django_db()
class TestAutocomplete:
    def call_view(self, rf, data):
        # pylint: disable=protected-access
        request = rf.get(f"/organizations/autocomplete/", data)
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
        self.assert_message(messages.ERROR, "Payment error: Error message")


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
class TestManageMembers(ViewTestMixin):
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
        data = {"action": "addmember", "email": email}
        self.call_view(rf, user, data, slug=organization.slug)
        assert organization.invitations.filter(email=email).exists()
        mail = mailoutbox[0]
        assert mail.subject == f"Invitation to join {organization.name}"
        assert mail.to == [email]
        self.assert_message(messages.SUCCESS, "Invitation sent")

    def test_add_member_bad_email(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        email = "not an email"
        data = {"action": "addmember", "email": email}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "Please enter a valid email address")

    def test_add_member_bad_user_limit(self, rf, organization_factory, user_factory):
        user = user_factory()
        members = user_factory.create_batch(4)
        organization = organization_factory(admins=[user], users=members, max_users=5)
        email = "invite@example.com"
        data = {"action": "addmember", "email": email}
        self.call_view(rf, user, data, slug=organization.slug)
        self.assert_message(
            messages.ERROR,
            "You need to increase your max users to invite another member",
        )

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
        self.assert_message(messages.SUCCESS, "Invitation revoked")

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
        self.assert_message(messages.SUCCESS, "Invitation accepted")

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
        self.assert_message(messages.SUCCESS, "Invitation rejected")

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
        self.assert_message(messages.SUCCESS, "Made an admin")

    def test_remove_admin(self, rf, organization_factory, user_factory):
        admins = user_factory.create_batch(2)
        organization = organization_factory(admins=admins)
        data = {"action": "makeadmin", "userid": admins[1].pk, "admin": "false"}
        self.call_view(rf, admins[0], data, slug=organization.slug)
        assert not organization.has_admin(admins[1])
        self.assert_message(messages.SUCCESS, "Made not an admin")

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
        self.assert_message(messages.SUCCESS, "Removed user")

    def test_bad_action(self, rf, organization_factory, user_factory):
        admin = user_factory()
        organization = organization_factory(admins=[admin])
        data = {"action": "fakeaction"}
        self.call_view(rf, admin, data, slug=organization.slug)
        self.assert_message(messages.ERROR, "An unexpected error occurred")


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


@pytest.mark.django_db()
class TestReceipts(ViewTestMixin):
    """Test the Organization Receipts view"""

    view = views.Receipts
    url = "/organizations/{slug}/receipts/"

    def test_get_admin(self, rf, organization_factory, user_factory, charge_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        charge_factory(organization=organization)
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert list(response.context_data["charges"]) == list(
            organization.charges.all()
        )


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
        # pylint: disable=protected-access
        request = rf.post(
            f"/organizations/~stripe_webhook/",
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
        request = rf.get(f"/organizations/~stripe_webhook/")
        response = views.stripe_webhook(request)
        assert response.status_code == 405

    def test_bad_json(self, rf):
        """Malformed JSON should fail"""
        request = rf.post(
            f"/organizations/~stripe_webhook/",
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

    @override_settings(STRIPE_WEBHOOK_SECRET="123")
    def test_signature_verification(self, rf):
        """Signature verification error should fail"""
        event = {"type": "test"}
        response = self.call_view(rf, event)
        assert response.status_code == 400
