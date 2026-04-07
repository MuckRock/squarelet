# Third Party
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)


def make_searchable(user):
    """Make a user visible in search by marking their individual org as not hidden."""
    org = user.individual_organization
    org.hidden = False
    org.private = False
    org.save()


@pytest.mark.django_db()
class TestUserSearchAPI:
    """Tests for the /fe_api/users/ search endpoint"""

    def test_anonymous_returns_empty(self, user_factory):
        """Anonymous requests should get an empty list, not a redirect"""
        user_factory.create_batch(3)
        client = APIClient()
        response = client.get("/fe_api/users/?format=json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_verified_journalist_sees_email(self, user_factory):
        """Verified journalists should see email in search results"""
        org = OrganizationFactory(verified_journalist=True)
        requester = user_factory()
        MembershipFactory(user=requester, organization=org)
        target = user_factory()
        make_searchable(target)

        client = APIClient()
        client.force_authenticate(user=requester)
        response = client.get(
            "/fe_api/users/", {"search": target.username, "format": "json"}
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) >= 1
        result = next(r for r in results if r["id"] == target.id)
        assert "email" in result

    def test_non_verified_user_no_email(self, user_factory):
        """Non-verified users should not see email in search results"""
        requester = user_factory()
        requester.organizations.update(verified_journalist=False)
        target = user_factory()
        make_searchable(target)

        client = APIClient()
        client.force_authenticate(user=requester)
        response = client.get(
            "/fe_api/users/", {"search": target.username, "format": "json"}
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) >= 1
        result = next(r for r in results if r["id"] == target.id)
        assert "email" not in result
