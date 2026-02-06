"""Tests for organization forms"""

# Third Party
import pytest

# Squarelet
from squarelet.organizations.forms import ProfileChangeRequestForm
from squarelet.organizations.models import ProfileChangeRequest


@pytest.mark.django_db()
class TestProfileChangeRequestForm:
    """Test ProfileChangeRequestForm"""

    def test_unchanged_fields_are_cleared(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that fields with unchanged values are cleared"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
            city="Original City",
            state="NY",
            country="US",
        )
        user = user_factory()
        request = rf.post("/")
        request.user = user

        # Create form with initial values from organization
        form_data = {
            "name": "Original Name",  # Unchanged
            "slug": "new-slug",  # Changed
            "city": "Original City",  # Unchanged
            "state": "CA",  # Changed
            "country": "US",  # Unchanged
            "explanation": "Updating slug and state",
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
            "city": org.city,
            "state": org.state,
            "country": org.country,
        }

        instance = ProfileChangeRequest(organization=org, user=user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert form.is_valid(), form.errors
        cleaned = form.cleaned_data

        # Unchanged fields should be cleared
        assert cleaned["name"] == ""
        assert cleaned["city"] == ""
        assert cleaned["country"] == ""

        # Changed fields should remain
        assert cleaned["slug"] == "new-slug"
        assert cleaned["state"] == "CA"

    def test_requires_at_least_one_change(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that form requires at least one field to be changed"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
            city="Original City",
            state="NY",
            country="US",
        )
        user = user_factory()
        request = rf.post("/")
        request.user = user

        # Submit form with no changes
        form_data = {
            "name": "Original Name",
            "slug": "original-slug",
            "city": "Original City",
            "state": "NY",
            "country": "US",
            "explanation": "No actual changes",
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
            "city": org.city,
            "state": org.state,
            "country": org.country,
        }

        instance = ProfileChangeRequest(organization=org, user=user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert not form.is_valid()
        assert "You must change at least one field." in str(form.errors)

    def test_staff_user_does_not_require_explanation(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that staff users don't need to provide an explanation"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
        )
        staff_user = user_factory(is_staff=True)
        request = rf.post("/")
        request.user = staff_user

        form_data = {
            "name": "New Name",
            "slug": "original-slug",
            "explanation": "",  # No explanation
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
        }

        instance = ProfileChangeRequest(organization=org, user=staff_user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert form.is_valid(), form.errors

    def test_non_staff_user_requires_explanation(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that non-staff users must provide an explanation"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
        )
        user = user_factory(is_staff=False)
        request = rf.post("/")
        request.user = user

        form_data = {
            "name": "New Name",
            "slug": "original-slug",
            "explanation": "",  # No explanation
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
        }

        instance = ProfileChangeRequest(organization=org, user=user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert not form.is_valid()
        assert "Please provide an explanation for your requested changes." in str(
            form.errors
        )

    def test_url_field_accepts_new_url(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that URL field accepts new URLs even when not initially set"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
        )
        user = user_factory()
        request = rf.post("/")
        request.user = user

        form_data = {
            "name": "Original Name",
            "slug": "original-slug",
            "url": "https://example.com",  # New URL
            "explanation": "Adding organization URL",
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
        }

        instance = ProfileChangeRequest(organization=org, user=user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["url"] == "https://example.com"

    def test_url_must_be_unique_for_organization(
        self, organization_factory, user_factory, rf  # pylint: disable=invalid-name
    ):
        """Test that duplicate URLs are rejected for the same organization"""
        org = organization_factory(
            name="Original Name",
            slug="original-slug",
        )
        # Add an existing URL to the organization
        org.urls.create(url="https://existing.com")

        user = user_factory()
        request = rf.post("/")
        request.user = user

        form_data = {
            "name": "Original Name",
            "slug": "original-slug",
            "url": "https://existing.com",  # Duplicate URL
            "explanation": "Adding existing URL",
        }

        initial = {
            "name": org.name,
            "slug": org.slug,
        }

        instance = ProfileChangeRequest(organization=org, user=user)
        form = ProfileChangeRequestForm(
            data=form_data, instance=instance, request=request, initial=initial
        )

        assert not form.is_valid()
        assert "url" in form.errors
        assert "already associated with the organization" in str(form.errors["url"])
