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

# pylint: disable=invalid-name


@pytest.mark.django_db()
class TestDetail:
    def call_view(self, rf, organization, user=None, data=None):
        # pylint: disable=protected-access
        if user is None:
            user = AnonymousUser()
        if data is None:
            request = rf.get(f"/organizations/{organization.slug}/")
        else:
            request = rf.post(f"/organizations/{organization.slug}/", data)
        request.user = user
        request._messages = MagicMock()
        return views.Detail.as_view()(request, slug=organization.slug)

    def test_get_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, organization)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization

    def test_get_member(self, rf, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(users=[user])
        response = self.call_view(rf, organization, user)
        assert response.status_code == 200
        assert response.context_data["organization"] == organization
        assert not response.context_data["is_admin"]
        assert response.context_data["is_member"]
        assert "requested_invite" in response.context_data
        assert "invite_count" not in response.context_data

    def test_get_admin(self, rf, organization_factory, user_factory):
        user = user_factory(password="password")
        organization = organization_factory(admins=[user])
        response = self.call_view(rf, organization, user)
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
            self.call_view(rf, organization)

    def test_post_anonymous(self, rf, organization_factory):
        organization = organization_factory()
        response = self.call_view(rf, organization, data={"action": "join"})
        assert response.status_code == 302

    def test_post_join(self, rf, mailoutbox, organization_factory, user_factory):
        admin, joiner = user_factory.create_batch(2)
        organization = organization_factory(admins=[admin])
        response = self.call_view(rf, organization, joiner, {"action": "join"})
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
        response = self.call_view(rf, organization, joiner, {"action": "join"})
        assert response.status_code == 302
        assert not organization.invitations.filter(
            email=joiner.email, user=joiner, request=True
        ).exists()
        assert not mailoutbox

    def test_post_member_leave(self, rf, organization_factory, user_factory):
        admin, leaver = user_factory.create_batch(2)
        organization = organization_factory(admins=[admin], users=[leaver])
        response = self.call_view(rf, organization, leaver, {"action": "leave"})
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
        # sort? order by name second?
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
