# test_viewsets.py

# Third Party
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.organizations.models import Membership, Organization
from squarelet.users.models import User


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user_with_org(db):
    user = User.objects.create_user(
        username="user1", email="user1@example.com", password="password"
    )
    org = Organization.objects.create(name="Org A")
    Membership.objects.create(user=user, organization=org)
    return user, org


@pytest.fixture
def user_without_org(db):
    return User.objects.create_user(
        username="user2", email="user2@example.com", password="password"
    )


@pytest.mark.django_db
def test_list_users_authenticated(client, user_with_org, user_without_org):
    user, org = user_with_org
    # Make both users visible (un-hide them)
    user.individual_organization.hidden = False
    user.individual_organization.save()
    user_without_org.individual_organization.hidden = False
    user_without_org.individual_organization.save()

    client.force_authenticate(user=user)

    response = client.get("/fe_api/users/")
    results = response.data["results"]
    assert response.status_code == status.HTTP_200_OK
    assert len(results) == 2
    assert all("id" in u and "username" in u for u in results)


@pytest.mark.django_db
def test_user_detail_with_shared_org(client, user_with_org):
    user, org = user_with_org
    other_user = User.objects.create_user(username="shared", email="shared@example.com")
    Membership.objects.create(user=other_user, organization=org)

    client.force_authenticate(user=user)
    response = client.get(f"/fe_api/users/{other_user.id}/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["email"] == "shared@example.com"


@pytest.mark.django_db
def test_user_detail_no_shared_org(client, user_with_org, user_without_org):
    user, _ = user_with_org
    client.force_authenticate(user=user)

    response = client.get(f"/fe_api/users/{user_without_org.id}/")
    assert response.status_code == status.HTTP_200_OK
    assert "email" not in response.data
    assert "username" in response.data


@pytest.mark.django_db
def test_user_list_unauthenticated(client):
    response = client.get("/fe_api/users/")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_search_users_by_username(client, user_with_org):
    """Search endpoint filters by username"""
    user, _ = user_with_org
    # Make user1 searchable (not hidden)
    user.individual_organization.hidden = False
    user.individual_organization.save()

    other = User.objects.create_user(
        username="searchable", email="search@example.com", password="password"
    )
    other.individual_organization.hidden = False
    other.individual_organization.save()

    client.force_authenticate(user=user)
    response = client.get("/fe_api/users/?search=searchable", format="json")
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["username"] == "searchable"


@pytest.mark.django_db
def test_search_excludes_hidden_users(client, user_with_org):
    """Hidden users should not appear in search results"""
    user, _ = user_with_org
    hidden_user = User.objects.create_user(
        username="hidden_guy", email="hidden@example.com", password="password"
    )
    # hidden_guy's individual_organization.hidden defaults to True

    client.force_authenticate(user=user)
    response = client.get("/fe_api/users/?search=hidden_guy", format="json")
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert len(results) == 0


@pytest.mark.django_db
def test_search_list_fields(client, user_with_org):
    """Search results should include fields needed by UserSelect"""
    user, _ = user_with_org
    other = User.objects.create_user(
        username="visible", email="visible@example.com", password="password"
    )
    other.individual_organization.hidden = False
    other.individual_organization.save()

    client.force_authenticate(user=user)
    response = client.get("/fe_api/users/?search=visible", format="json")
    results = response.data["results"]
    assert len(results) == 1
    assert "email" in results[0]
    assert "username" in results[0]
    assert "name" in results[0]
    assert "avatar_url" in results[0]
