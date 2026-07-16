"""
Tests for OIDC views
"""

# Django
from django.test import Client as DjangoTestClient
from django.urls import reverse

# Third Party
import pytest
from oidc_provider.models import ResponseType

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory, ClientProfileFactory
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)
from squarelet.users.tests.factories import UserFactory

NOTICE_TEMPLATE = "oidc_provider/verification_notice.html"


def templates_used(response):
    return {template.name for template in response.templates}


@pytest.mark.django_db()
class TestAuthorizeVerificationNotice:
    """The authorize endpoint interposes an informational verification notice
    for unverified users of clients that gate features behind verification."""

    def _make_client(self, *, checks_verification=False, verification_notice=""):
        response_type, _ = ResponseType.objects.get_or_create(
            value="code", defaults={"description": "Authorization Code Flow"}
        )
        client = ClientFactory(client_type="confidential", require_consent=False)
        client.redirect_uris = ["https://example.com/callback/"]
        client.save()
        client.response_types.add(response_type)
        ClientProfileFactory(
            client=client,
            checks_verification=checks_verification,
            verification_notice=verification_notice,
        )
        return client

    def _authorize_params(self, client, **extra):
        params = {
            "client_id": client.client_id,
            "redirect_uri": "https://example.com/callback/",
            "scope": "openid profile email",
            "response_type": "code",
            "state": "abc123",
        }
        params.update(extra)
        return params

    def _authorize(self, http, oidc_client, **extra):
        return http.get(
            reverse("oidc_provider:authorize"),
            self._authorize_params(oidc_client, **extra),
        )

    def test_notice_shown_to_unverified_user_of_gated_client(self):
        oidc_client = self._make_client(
            checks_verification=True,
            verification_notice="Uploads require a verified newsroom.",
        )
        user = UserFactory(
            individual_organization__verified_journalist=False,
            email_verified=True,
        )
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        assert response.status_code == 200
        assert NOTICE_TEMPLATE in templates_used(response)
        assert b"Uploads require a verified newsroom." in response.content

    def test_verification_notice_renders_markdown(self):
        oidc_client = self._make_client(
            checks_verification=True,
            verification_notice="Uploads need a **verified** newsroom.",
        )
        user = UserFactory(
            individual_organization__verified_journalist=False,
            email_verified=True,
        )
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        # markdown is rendered to HTML, not shown as literal asterisks
        assert b"<strong>verified</strong>" in response.content
        assert b"**verified**" not in response.content

    def test_lists_unverified_orgs_with_prefilled_links(self):
        oidc_client = self._make_client(checks_verification=True)
        user = UserFactory(
            individual_organization__verified_journalist=False,
            email_verified=True,
        )
        org = OrganizationFactory(name="AcmeNewsroom", verified_journalist=False)
        MembershipFactory(user=user, organization=org)
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)
        content = response.content.decode()

        # the org is listed with a verification link prefilled for that org
        assert "AcmeNewsroom" in content
        assert 'class="request-verification' in content
        # the airtable link carries an org-specific prefill value
        assert "prefill_" in content
        assert "AcmeNewsroom" in content.split("prefill_", 1)[1]

    def test_offers_individual_verification_when_no_orgs(self):
        oidc_client = self._make_client(checks_verification=True)
        user = UserFactory(
            individual_organization__verified_journalist=False,
            email_verified=True,
        )
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        # with no member orgs, the individual verification option is offered
        assert response.content.count(b'class="request-verification') == 1

    def test_verification_gated_without_confirmed_email(self):
        oidc_client = self._make_client(checks_verification=True)
        org = OrganizationFactory(name="AcmeNewsroom", verified_journalist=False)
        user = UserFactory(
            individual_organization__verified_journalist=False,
            email_verified=False,
        )
        MembershipFactory(user=user, organization=org)
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        # the notice still shows, but verification links are withheld until
        # the user confirms an email address
        assert NOTICE_TEMPLATE in templates_used(response)
        assert b'class="request-verification' not in response.content
        assert b"Confirm your account" in response.content

    def test_verified_user_skips_notice(self):
        oidc_client = self._make_client(checks_verification=True)
        # a plain user is verified via their (default-verified) individual org
        user = UserFactory()
        assert user.verified_journalist()
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        assert response.status_code == 302
        assert NOTICE_TEMPLATE not in templates_used(response)

    def test_ungated_client_skips_notice(self):
        oidc_client = self._make_client(checks_verification=False)
        user = UserFactory(individual_organization__verified_journalist=False)
        http = DjangoTestClient()
        http.force_login(user)

        response = self._authorize(http, oidc_client)

        assert response.status_code == 302
        assert NOTICE_TEMPLATE not in templates_used(response)

    def test_acknowledging_proceeds_and_dismisses_for_session(self):
        oidc_client = self._make_client(checks_verification=True)
        user = UserFactory(individual_organization__verified_journalist=False)
        http = DjangoTestClient()
        http.force_login(user)

        # continuing (verification_ack) proceeds past the notice ...
        ack = self._authorize(http, oidc_client, verification_ack="1")
        assert ack.status_code == 302
        assert NOTICE_TEMPLATE not in templates_used(ack)
        assert oidc_client.client_id in http.session["verification_notice_dismissed"]

        # ... and the notice stays dismissed on the next authorization
        again = self._authorize(http, oidc_client)
        assert again.status_code == 302
        assert NOTICE_TEMPLATE not in templates_used(again)

    def test_unauthenticated_user_redirected_to_login(self):
        oidc_client = self._make_client(checks_verification=True)

        response = self._authorize(DjangoTestClient(), oidc_client)

        assert response.status_code == 302
        assert response["Location"].startswith(reverse("account_login"))
        assert NOTICE_TEMPLATE not in templates_used(response)
