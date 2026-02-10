# Django
from django.template import Context, Template
from django.test import RequestFactory

# Standard Library
from urllib.parse import parse_qs, urlparse

# Third Party
import pytest

# Squarelet
from squarelet.core.templatetags.airtable import (
    airtable_form_url,
    airtable_verification_url,
)
from squarelet.organizations.models.organization_metadata import OrganizationUrl


class TestAirtableFormUrl:
    """Test the airtable_form_url template tag"""

    def test_base_url_no_params(self):
        """Should return base URL unchanged when no parameters provided"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url)
        assert result == base_url

    def test_base_url_empty_params(self):
        """Should return base URL unchanged when empty kwargs provided"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, **{})
        assert result == base_url

    def test_single_string_param(self):
        """Should generate URL with single prefilled parameter"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, name="John Doe")

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "airtable.com"
        assert parsed.path == "/form123"
        assert query_params["prefill_name"] == ["John Doe"]

    def test_multiple_string_params(self):
        """Should generate URL with multiple prefilled parameters"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(
            base_url, name="John Doe", email="john@example.com", company="Acme Corp"
        )

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert query_params["prefill_name"] == ["John Doe"]
        assert query_params["prefill_email"] == ["john@example.com"]
        assert query_params["prefill_company"] == ["Acme Corp"]

    def test_list_param_conversion(self):
        """Should convert list parameters to comma-separated strings"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, tags=["python", "django", "testing"])

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert query_params["prefill_tags"] == ["python,django,testing"]

    def test_mixed_list_types(self):
        """Should handle lists with mixed data types"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, items=[1, "two", 3.14, True])

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert query_params["prefill_items"] == ["1,two,3.14,True"]

    def test_none_values_filtered_out(self):
        """Should filter out None values from parameters"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, name="John Doe", email=None, company="")

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # None should be filtered out, empty string should be included
        assert "prefill_email" not in result
        assert query_params["prefill_name"] == ["John Doe"]
        assert "prefill_company=" in result

    def test_special_characters_encoded(self):
        """Should properly URL encode special characters"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(
            base_url,
            name="John & Jane Doe",
            message="Hello world! How are you?",
            symbols="@#$%^&*()",
        )

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # parse_qs automatically decodes, so we check the decoded values
        assert query_params["prefill_name"] == ["John & Jane Doe"]
        assert query_params["prefill_message"] == ["Hello world! How are you?"]
        assert query_params["prefill_symbols"] == ["@#$%^&*()"]

    def test_empty_list_param(self):
        """Should handle empty lists"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, tags=[])

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert "prefill_tags" not in query_params
        assert "prefill_tags=" in result

    def test_numeric_params(self):
        """Should convert numeric parameters to strings"""
        base_url = "https://airtable.com/form123"
        result = airtable_form_url(base_url, age=25, score=98.5, active=True)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        assert query_params["prefill_age"] == ["25"]
        assert query_params["prefill_score"] == ["98.5"]
        assert query_params["prefill_active"] == ["True"]


class TestAirtableVerificationUrl:
    """Test the airtable_verification_url template tag"""

    @pytest.fixture
    def mock_user(self, mocker):
        """Create a mock user with required methods"""
        user = mocker.MagicMock()
        user.get_full_name.return_value = "John Doe"
        user.username = "johndoe"
        user.email = "john@example.com"
        user.get_absolute_url.return_value = "/users/johndoe/"
        return user

    @pytest.fixture
    def mock_organization(self, mocker):
        """Create a mock organization with required attributes"""
        org = mocker.MagicMock()
        org.name = "Acme Corporation"
        org.get_absolute_url.return_value = "/organizations/acme/"
        return org

    @pytest.fixture
    def mock_context(self, mock_user):
        """Create a mock template context with request and user"""
        rf = RequestFactory()
        request = rf.get("/")
        request.user = mock_user
        return {"request": request}

    @pytest.mark.django_db(transaction=True)
    def test_complete_data(self, mock_context, organization_factory):
        """Should generate URL with all user and organization data"""
        rf = RequestFactory()
        request = rf.get("/")
        org = organization_factory(name="Acme Corporation", slug="acme")
        OrganizationUrl.objects.create(organization=org, url="https://acme.com")
        result = airtable_verification_url(mock_context, org)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Check base URL
        assert "airtable.com/app93Yt5cwdVWTnqn/pagogIhgB1jZTzq00/form" in result

        # Check all expected parameters are present
        assert query_params["prefill_Your Name"] == ["John Doe"]
        assert query_params["prefill_Email address on your account"] == [
            "john@example.com"
        ]
        assert query_params["prefill_Organization or Project Name"] == [
            "Acme Corporation"
        ]
        assert query_params["prefill_Organization URL"] == ["https://acme.com"]
        assert query_params["prefill_MR User Account URL"] == [
            request.build_absolute_uri("/users/johndoe/")
        ]
        assert query_params["prefill_MR Organization Account URL"] == [
            request.build_absolute_uri("/organizations/acme/")
        ]

    def test_user_without_full_name(self, mock_context, mock_organization):
        """Should use username when user has no full name"""
        # Mock user with no full name
        mock_context["request"].user.get_full_name.return_value = ""

        result = airtable_verification_url(mock_context, mock_organization)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Should use username as fallback
        assert query_params["prefill_Your Name"] == ["johndoe"]

    def test_user_with_none_full_name(self, mock_context, mock_organization):
        """Should use username when user.get_full_name() returns None"""
        # Mock user with None full name
        mock_context["request"].user.get_full_name.return_value = None

        result = airtable_verification_url(mock_context, mock_organization)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Should use username as fallback
        assert query_params["prefill_Your Name"] == ["johndoe"]

    def test_organization_without_url(self, mock_context, mock_organization):
        """Should handle organization without URL"""
        # Mock organization without URL
        rf = RequestFactory()
        request = rf.get("/")
        mock_organization.urls = OrganizationUrl.objects.none()

        result = airtable_verification_url(mock_context, mock_organization)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Organization URL should be filtered out
        assert "prefill_Organization URL" not in query_params
        # Other organization data should still be present
        assert query_params["prefill_Organization or Project Name"] == [
            "Acme Corporation"
        ]
        assert query_params["prefill_MR Organization Account URL"] == [
            request.build_absolute_uri("/organizations/acme/")
        ]

    def test_organization_with_empty_url(self, mock_context, mock_organization):
        """Should handle organization with empty URL"""
        # Mock organization with empty URL
        mock_organization.urls = OrganizationUrl.objects.none()

        result = airtable_verification_url(mock_context, mock_organization)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Empty URL should be filtered out
        assert "prefill_Organization URL" not in query_params

    def test_none_organization(self, mock_context):
        """Should handle None organization"""
        result = airtable_verification_url(mock_context, None)

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Should only have user data
        assert query_params["prefill_Your Name"] == ["John Doe"]
        assert query_params["prefill_Email address on your account"] == [
            "john@example.com"
        ]

        # Organization fields should be filtered out
        assert "prefill_Organization or Project Name" not in query_params
        assert "prefill_Organization URL" not in query_params
        assert "prefill_MR Organization Account URL" not in query_params

    def test_uses_verification_form_constant(self, mock_context, mock_organization):
        """Should use the VERIFICATION_FORM_URL constant"""
        result = airtable_verification_url(mock_context, mock_organization)

        # Should contain the verification form URL from the constant
        expected_base = "https://airtable.com/app93Yt5cwdVWTnqn/pagogIhgB1jZTzq00/form"
        assert result.startswith(expected_base)


class TestAirtableTemplateTagsInTemplate:
    """Test the template tags when used in actual Django templates"""

    def test_airtable_form_url_in_template(self):
        """Should work correctly when used in a Django template"""
        template = Template(
            "{% load airtable %}"
            "{% airtable_form_url 'https://airtable.com/form123' name='John' email='john@example.com' %}"
        )

        result = template.render(Context({}))

        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)
        assert query_params["prefill_name"] == ["John"]
        assert query_params["prefill_email"] == ["john@example.com"]

    @pytest.mark.django_db(transaction=True)
    def test_airtable_verification_url_in_template(
        self, user_factory, organization_factory
    ):
        """Should work correctly when used in a Django template with real models"""
        user = user_factory(name="Jane Doe", email="jane@example.com")
        organization = organization_factory(name="Test Org")

        rf = RequestFactory()
        request = rf.get("/")
        request.user = user

        template = Template(
            "{% load airtable %}" "{% airtable_verification_url organization %}"
        )

        context = Context({"request": request, "organization": organization})
        result = template.render(context)

        # Should generate a valid URL
        parsed = urlparse(result)
        assert parsed.netloc == "airtable.com"
        assert "prefill_Your%20Name" in result or "prefill_Your+Name" in result
        assert "Test+Org" in result or "Test%20Org" in result

    def test_template_tag_with_special_characters(self):
        """Should handle special characters in template context"""
        template = Template(
            "{% load airtable %}"
            "{% airtable_form_url base_url name=user_name message=user_message %}"
        )

        context = Context(
            {
                "base_url": "https://airtable.com/form123",
                "user_name": "John & Jane",
                "user_message": "Hello, world! How are you?",
            }
        )

        result = template.render(context)

        # Should properly encode special characters
        assert "John" in result
        assert "Jane" in result
        assert "Hello" in result
        assert "world" in result

    @pytest.mark.django_db()
    def test_integration_with_real_user_data(self, user_factory, organization_factory):
        """Integration test with real user and organization models"""
        # Create real user and organization
        user = user_factory(
            name="Integration Test User",
            email="integration@test.com",
            username="integrationuser",
        )
        organization = organization_factory(name="Integration Test Organization")

        # Create real request context
        rf = RequestFactory()
        request = rf.get("/test/")
        request.user = user

        context = {"request": request}

        # Test the template tag
        result = airtable_verification_url(context, organization)

        # Verify URL structure
        assert result.startswith(
            "https://airtable.com/app93Yt5cwdVWTnqn/pagogIhgB1jZTzq00/form"
        )

        # Parse and verify prefilled data
        parsed = urlparse(result)
        query_params = parse_qs(parsed.query)

        # Check user data
        expected_name = user.get_full_name() or user.username
        assert query_params["prefill_Your Name"] == [expected_name]
        assert query_params["prefill_Email address on your account"] == [user.email]

        # Check organization data
        assert query_params["prefill_Organization or Project Name"] == [
            organization.name
        ]

        # Check URLs (using real get_absolute_url methods)
        assert query_params["prefill_MR User Account URL"] == [
            request.build_absolute_uri(user.get_absolute_url())
        ]
        assert query_params["prefill_MR Organization Account URL"] == [
            request.build_absolute_uri(organization.get_absolute_url())
        ]
