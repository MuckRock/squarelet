# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import ProfileChangeRequest


class TestProfileChangeRequest:
    """Unit tests for ProfileChangeRequest model"""

    @pytest.mark.django_db()
    def test_str(self, profile_change_request_factory):
        """Test string representation"""
        request = profile_change_request_factory()
        assert str(request) == f"Request: {request.organization} by {request.user}"

    @pytest.mark.django_db()
    def test_save_populates_previous(self, profile_change_request_factory):
        """Test that save() auto-populates previous field with org's current values"""
        request = profile_change_request_factory(
            previous=None, name="New Name", city="New City"
        )

        # previous should be populated with org's original values
        assert request.previous is not None
        assert request.previous["name"] == request.organization.name
        assert request.previous["slug"] == request.organization.slug
        assert request.previous["city"] == request.organization.city
        assert request.previous["state"] == request.organization.state
        assert request.previous["country"] == request.organization.country

    @pytest.mark.django_db()
    def test_save_does_not_overwrite_previous(self, profile_change_request_factory):
        """Test that save() doesn't overwrite existing previous field"""
        original_previous = {
            "name": "Original Name",
            "slug": "original-slug",
            "city": "Original City",
            "state": "CA",
            "country": "US",
        }
        request = profile_change_request_factory(previous=original_previous)

        # Update and save again
        request.name = "Updated Name"
        request.save()

        # previous should remain unchanged
        assert request.previous == original_previous

    @pytest.mark.django_db(transaction=True)
    def test_accept_updates_organization(self, profile_change_request_factory, mocker):
        """Test that accept() updates organization with requested changes"""
        mocked_sci = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )

        request = profile_change_request_factory(
            status="pending",
            name="New Org Name",
            city="New City",
            state="NY",
            country="US",
        )

        request.accept()

        # Status should be updated
        assert request.status == "accepted"

        # Organization should be updated with new values
        request.organization.refresh_from_db()
        assert request.organization.name == "New Org Name"
        assert request.organization.city == "New City"
        assert request.organization.state == "NY"
        assert request.organization.country == "US"

        # Cache invalidation should be called
        mocked_sci.assert_called_with("organization", request.organization.uuid)

    @pytest.mark.django_db(transaction=True)
    def test_accept_only_updates_non_blank_fields(
        self, profile_change_request_factory, mocker
    ):
        """Test that accept() only updates fields that have values"""
        mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )

        org_city = "Original City"
        org_state = "CA"
        request = profile_change_request_factory(
            status="pending",
            name="New Name",
            city="",  # blank, should not update
            state=org_state,
            country="",  # blank, should not update
        )

        # Set organization city and country
        request.organization.city = org_city
        request.organization.country = "US"
        request.organization.save()

        request.accept()

        request.organization.refresh_from_db()
        # Name should be updated
        assert request.organization.name == "New Name"
        # City should remain unchanged (blank in request)
        assert request.organization.city == org_city
        # Country should remain unchanged (blank in request)
        assert request.organization.country == "US"

    @pytest.mark.django_db()
    def test_reject_updates_status(self, profile_change_request_factory):
        """Test that reject() updates status but doesn't modify organization"""
        request = profile_change_request_factory(
            status="pending", name="New Name", city="New City"
        )

        original_org_name = request.organization.name

        request.reject()

        # Status should be updated
        assert request.status == "rejected"

        # Organization should remain unchanged
        request.organization.refresh_from_db()
        assert request.organization.name == original_org_name

    @pytest.mark.django_db()
    def test_default_status_is_pending(self, profile_change_request_factory):
        """Test that new requests default to pending status"""
        request = profile_change_request_factory()
        assert request.status == "pending"

    @pytest.mark.django_db()
    def test_all_fields_tracked_in_previous(self, organization_factory, user_factory):
        """Test that all FIELDS are tracked in previous snapshot"""

        org = organization_factory(
            name="Test Org", slug="test-org", city="Test City", state="CA", country="US"
        )
        user = user_factory()

        request = ProfileChangeRequest.objects.create(
            organization=org, user=user, name="New Name"
        )

        # All fields in FIELDS tuple should be in previous
        for field in ProfileChangeRequest.FIELDS:
            assert field in request.previous
            assert request.previous[field] == getattr(org, field)
