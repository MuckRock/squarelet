# Django
from django.contrib.auth.models import AnonymousUser
from django.http.response import Http404

# Standard Library
import json
from unittest.mock import MagicMock

# Third Party
import pytest

# Squarelet
from squarelet.organizations import views
from squarelet.organizations.models import ReceiptEmail

# pylint: disable=invalid-name


class ViewTest:
    def call_view(self, rf, user=None, data=None, **kwargs):
        # pylint: disable=protected-access
        url = self.url.format(**kwargs)
        if user is None:
            user = AnonymousUser()
        if data is None:
            request = rf.get(url)
        else:
            request = rf.post(url, data)
        request.user = user
        request._messages = MagicMock()
        request.session = MagicMock()
        return self.view.as_view()(request, **kwargs)


@pytest.mark.django_db()
class TestDetail(ViewTest):
    """Test the Organization Detail view"""

    view = views.Detail
    url = "/organizations/{slug}/"

    def test_get_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization

    def test_get_member(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(users=[user])
        response = self.call_view(rf, user, slug=organization.slug)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
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
            response = self.call_view(rf, user, slug=organization.slug)

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
        orgs = organization_factory.create_batch(5)
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
class TestUpdateSubscription:
    def call_view(self, rf, organization, user=None, data=None):
        # pylint: disable=protected-access
        if user is None:
            user = AnonymousUser()
        if data is None:
            request = rf.get(f"/organizations/{organization.slug}/update/")
        else:
            request = rf.post(f"/organizations/{organization.slug}/update/", data)
        request.user = user
        request._messages = MagicMock()
        return views.UpdateSubscription.as_view()(request, slug=organization.slug)

    def test_get_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, organization)
        assert response.status_code == 302

    def test_get_admin(self, rf, organization_factory, user_factory, mocker):
        mocker.patch("squarelet.organizations.models.Organization.card", None)
        user = user_factory()
        organization = organization_factory(admins=[user])
        ReceiptEmail.objects.create(
            organization=organization, email="receipts@example.com", failed=False
        )
        failed_email = ReceiptEmail.objects.create(
            organization=organization, email="failed@example.com", failed=True
        )
        response = self.call_view(rf, organization, user)
        assert response.status_code == 200
        assert response.context_data["failed_receipt_emails"][0] == failed_email
        initial = response.context_data["form"].initial
        assert initial["plan"] == organization.plan
        assert initial["max_users"] == organization.max_users
        assert len(initial["receipt_emails"].split("\n")) == 2

    def test_post_admin(self, rf, organization_factory, user_factory, mocker):
        mocker.patch("squarelet.organizations.models.Organization.card", None)
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.set_subscription"
        )
        user = user_factory()
        organization = organization_factory(admins=[user])
        data = {
            "stripe_token": "token",
            "plan": organization.plan.pk,
            "max_users": 6,
            "receipt_emails": "receipt1@example.com\nreceipt2@example.com",
            "stripe_pk": "key",
        }
        response = self.call_view(rf, organization, user, data)
        assert response.status_code == 302
        assert mocked.called_with(
            token=data["stripe_token"],
            plan=organization.plan,
            max_user=data["max_users"],
        )
        assert set(e.email for e in organization.receipt_emails.all()) == set(
            data["receipt_emails"].split("\n")
        )


@pytest.mark.django_db()
class TestCreate(ViewTest):
    """Test the Organization Create view"""

    view = views.Create
    url = "/organizations/~create/"

    def test(self, rf, user_factory):
        user = user_factory()
        self.call_view(rf, user, {"name": "test"})
        organization = user.organizations.get(individual=False)
        assert organization.plan.slug == "free"
        assert organization.has_admin(user)
        assert user.email in organization.receipt_emails.values_list("email", flat=True)


@pytest.mark.django_db()
class TestInvitationAccept(ViewTest):
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
