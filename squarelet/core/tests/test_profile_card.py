# Django
from django.template import Context, Template
from django.utils import timezone

# Standard Library
import re
from datetime import timedelta

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import OrganizationFactory
from squarelet.services.tests.factories import ServiceFactory
from squarelet.users.tests.factories import UserFactory


def _render(entity, subject, **kwargs):
    args = " ".join(f"{key}={key}" for key in kwargs)
    template = Template(
        "{% load profile_card %}"
        f'{{% profile_card entity subject="{subject}" {args} %}}'
    )
    return template.render(Context({"entity": entity, **kwargs}))


@pytest.fixture(name="services")
def fixture_services():
    return {
        "muckrock": ServiceFactory(slug="muckrock", name="MuckRock"),
        "documentcloud": ServiceFactory(slug="documentcloud", name="DocumentCloud"),
    }


@pytest.mark.django_db
@pytest.mark.usefixtures("services")
class TestProfileCard:
    def test_a_new_user_sees_no_requests(self):
        user = UserFactory(client_stats={})

        html = _render(user, "users", show_stats=True)

        assert "No requests" in html
        assert "DocumentCloud" not in html
        assert "Last request" not in html

    def test_unverified_user_without_documents_has_no_documentcloud_line(self):
        user = UserFactory(
            client_stats={
                "muckrock": {"total_requests": 3},
                "documentcloud": {"total_documents": 0},
            }
        )

        html = _render(user, "users", verified=False, show_stats=True)

        assert "3 requests" in html
        assert "DocumentCloud" not in html

    def test_verified_user_without_documents_sees_no_documents(self):
        user = UserFactory(client_stats={})

        html = _render(user, "users", verified=True, show_stats=True)

        assert "No documents" in html
        assert "Verified" in html

    def test_unverified_user_with_documents_sees_them(self):
        user = UserFactory(client_stats={"documentcloud": {"total_documents": 4}})

        html = _render(user, "users", verified=False, show_stats=True)

        assert "4 documents" in html

    def test_counts_pluralize_and_show_last_activity(self):
        two_weeks_ago = (timezone.now() - timedelta(days=15)).isoformat()
        user = UserFactory(
            client_stats={
                "muckrock": {"total_requests": 1, "last_request_at": two_weeks_ago},
                "documentcloud": {
                    "total_documents": 16,
                    "last_upload_at": two_weeks_ago.replace("+00:00", "Z"),
                },
            }
        )

        html = _render(user, "users", show_stats=True)

        assert re.search(r"\b1 request\s*<", html)
        assert "16 documents" in html
        assert "Last request" in html
        assert "Last upload" in html
        assert "2\xa0weeks ago" in html
        assert "days" not in html

    def test_synced_at_key_is_not_rendered_as_a_service(self):
        user = UserFactory(client_stats={"synced_at": "2026-10-01T01:30:00+00:00"})

        html = _render(user, "users", show_stats=True)

        assert "synced_at" not in html
        assert html.count('class="profile-service"') == 1

    def test_service_without_a_service_row_is_skipped(self, services):
        services["muckrock"].delete()
        user = UserFactory(client_stats={"muckrock": {"total_requests": 3}})

        html = _render(user, "users", show_stats=True)

        assert "requests" not in html

    def test_user_card_shows_username_under_name_and_join_date(self):
        user = UserFactory(name="Alex Morgan", username="amorgan")

        html = _render(user, "users")

        assert "Alex Morgan" in html
        assert ">amorgan<" in html
        assert "Joined" in html

    def test_org_stats_hidden_when_show_stats_is_false(self):
        organization = OrganizationFactory(
            client_stats={"muckrock": {"total_requests": 3}}
        )

        html = _render(organization, "organizations", show_stats=False)

        assert "profile-services" not in html
        assert "requests" not in html

    def test_org_card_shows_location_and_about(self):
        organization = OrganizationFactory(
            name="The Daily Planet",
            city="Metropolis",
            state="NY",
            country="CA",
            about="Truth, justice.",
        )

        html = _render(organization, "organizations")

        assert "The Daily Planet" in html
        assert "Metropolis, New York, Canada" in html
        assert "Truth, justice." in html
        assert "Joined" not in html
