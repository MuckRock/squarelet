# Django
from django.urls import reverse

# Third Party
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.organizations.models import Membership, Organization
from squarelet.users.models import User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_organization_viewset_admins_field(api_client):
    user = User.objects.create_user(username="admin_user", password="pw")
    member = User.objects.create_user(username="member_user", password="pw")
    org = Organization.objects.create(name="Test Org", verified_journalist=True)

    Membership.objects.create(user=user, organization=org, admin=True)
    Membership.objects.create(user=member, organization=org, admin=False)

    api_client.force_authenticate(user=user)
    response = api_client.get(f"/fe_api/organizations/{org.id}/")
    assert response.status_code == status.HTTP_200_OK

    data = response.data
    assert user.id in data["admins"]
    assert member.id not in data["admins"]


@pytest.mark.django_db
def test_individual_org_excludes_admins_and_member_count(api_client):
    user = User.objects.create_user(username="user", password="pw")
    org = Organization.objects.create(
        name="Solo Org", individual=True, verified_journalist=True
    )

    api_client.force_authenticate(user=user)
    response = api_client.get(f"/fe_api/organizations/{org.id}/")
    assert response.status_code == status.HTTP_200_OK

    data = response.data
    assert "admins" not in data
    assert "member_count" not in data


@pytest.mark.django_db
def test_excludes_members_if_not_authenticated(api_client):
    user = User.objects.create_user(username="user", password="pw")
    org = Organization.objects.create(
        name="Private Org", private=True, verified_journalist=True
    )
    Membership.objects.create(user=user, organization=org)

    response = api_client.get(f"/fe_api/organizations/{org.id}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_excludes_members_if_user_not_member(api_client):
    user = User.objects.create_user(username="user", password="pw")
    non_member = User.objects.create_user(username="non_member", password="pw")
    org = Organization.objects.create(name="Some Org", verified_journalist=True)
    Membership.objects.create(user=user, organization=org)

    api_client.force_authenticate(user=non_member)
    response = api_client.get(f"/fe_api/organizations/{org.id}/")
    assert response.status_code == status.HTTP_200_OK

    data = response.data
    assert "users" not in data


@pytest.mark.django_db
def test_includes_members_if_user_is_member(api_client):
    user = User.objects.create_user(username="user", password="pw")
    org = Organization.objects.create(name="Some Org", verified_journalist=True)
    Membership.objects.create(user=user, organization=org)

    api_client.force_authenticate(user=user)
    response = api_client.get(f"/fe_api/organizations/{org.id}/")
    assert response.status_code == status.HTTP_200_OK

    data = response.data
    assert "users" in data
    assert user.id in data["users"]


@pytest.mark.django_db
def test_list_invitations(api_client, user_factory, invitation_factory):
    user = user_factory(email_verified=True)
    invitation = invitation_factory(user=user)

    api_client.force_authenticate(user)
    url = reverse("fe_api:fe-invitations-list")
    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert any(
        str(invitation.uuid) == str(item["uuid"]) for item in response.data["results"]
    )


@pytest.mark.django_db
def test_accept_invitation_as_invitee(api_client, user_factory, invitation_factory):
    user = user_factory(email_verified=True)
    invitation = invitation_factory(email=user.email, request=False)

    api_client.force_authenticate(user)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "accept"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "invitation accepted"


@pytest.mark.django_db
def test_accept_invitation_as_org_admin(
    api_client, user_factory, organization_factory, invitation_factory
):
    org = organization_factory()
    admin = user_factory(email_verified=True)
    org.memberships.create(user=admin, admin=True)

    join_request = invitation_factory(organization=org, request=True)

    api_client.force_authenticate(admin)
    url = reverse("fe_api:fe-invitations-detail", args=[join_request.pk])
    response = api_client.patch(url, data={"action": "accept"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "invitation accepted"


@pytest.mark.django_db
def test_accept_invitation_forbidden_for_unrelated_user(
    api_client, user_factory, invitation_factory
):
    unrelated_user = user_factory(email_verified=True)
    # Create invitation with a different email to ensure no match
    invitation = invitation_factory(email="invitation@different-domain.com")

    api_client.force_authenticate(unrelated_user)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "accept"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_reject_invitation_as_invitee(api_client, user_factory, invitation_factory):
    user = user_factory(email_verified=True)
    invitation = invitation_factory(email=user.email)

    api_client.force_authenticate(user)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "reject"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "invitation rejected"


@pytest.mark.django_db
def test_resend_invitation_as_admin(
    api_client, user_factory, organization_factory, invitation_factory
):
    org = organization_factory()
    admin = user_factory(email_verified=True)
    org.memberships.create(user=admin, admin=True)

    invitation = invitation_factory(organization=org)

    api_client.force_authenticate(admin)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "resend"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "invitation resent"


@pytest.mark.django_db
def test_invalid_action_returns_bad_request(
    api_client, user_factory, invitation_factory
):
    user = user_factory(email_verified=True)
    invitation = invitation_factory(user=user)

    api_client.force_authenticate(user)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "explode"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid action" in response.data["detail"]


@pytest.mark.django_db
def test_user_cannot_accept_own_join_request(
    api_client, user_factory, organization_factory, invitation_factory
):
    user = user_factory(email_verified=True)
    org = organization_factory()
    join_request = invitation_factory(
        email=user.email, user=user, organization=org, request=True
    )

    api_client.force_authenticate(user)
    url = reverse("fe_api:fe-invitations-detail", args=[join_request.pk])
    response = api_client.patch(url, data={"action": "accept"}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_member_cannot_resend_invitation(
    api_client, user_factory, organization_factory, invitation_factory
):
    org = organization_factory()
    member = user_factory(email_verified=True)
    org.memberships.create(user=member, admin=False)

    # Create invitation with different email to ensure no match
    invitation = invitation_factory(
        organization=org, email="different-invitation@example.com"
    )

    api_client.force_authenticate(member)
    url = reverse("fe_api:fe-invitations-detail", args=[invitation.pk])
    response = api_client.patch(url, data={"action": "resend"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_non_admin_cannot_create_invitation(
    api_client, user_factory, organization_factory
):
    org = organization_factory()
    member = user_factory(email_verified=True)
    org.memberships.create(user=member, admin=False)

    api_client.force_authenticate(member)
    url = reverse("fe_api:fe-invitations-list")
    response = api_client.post(
        url,
        data={"email": "invitee@example.com", "organization": org.pk, "request": False},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
