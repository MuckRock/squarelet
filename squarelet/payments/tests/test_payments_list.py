# Django
from django.urls import reverse

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.views import subscription as org_views
from squarelet.users import views as user_views


@pytest.mark.django_db()
class TestOrganizationPaymentsListNav(ViewTestMixin):
    """The org payment history sidebar navigates across the user's accounts."""

    view = org_views.PaymentsList
    url = "/organizations/{slug}/payments/"

    def test_nav_includes_personal_account_and_admin_orgs(
        self, rf, user_factory, organization_factory, membership_factory
    ):
        """The sidebar lists the personal account and every administered org,
        but not orgs where the user is only a member."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        member_org = organization_factory()
        membership_factory(user=user, organization=member_org, admin=False)

        response = self.call_view(rf, user, slug=org.slug)

        nav_orgs = [
            account["organization"] for account in response.context_data["nav_accounts"]
        ]
        assert user.individual_organization in nav_orgs
        assert org in nav_orgs
        assert member_org not in nav_orgs

    def test_current_org_is_active(self, rf, user_factory, organization_factory):
        """The organization being viewed is flagged active; the others are not."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)

        response = self.call_view(rf, user, slug=org.slug)

        accounts = {
            account["organization"]: account
            for account in response.context_data["nav_accounts"]
        }
        assert accounts[org]["active"] is True
        assert accounts[user.individual_organization]["active"] is False

    def test_nav_links_to_each_accounts_payment_history(
        self, rf, user_factory, organization_factory
    ):
        """Each nav entry links to that account's payment history page."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)

        response = self.call_view(rf, user, slug=org.slug)

        accounts = {
            account["organization"]: account
            for account in response.context_data["nav_accounts"]
        }
        assert accounts[org]["url"] == reverse(
            "organizations:payments", kwargs={"slug": org.slug}
        )
        assert accounts[user.individual_organization]["url"] == reverse(
            "users:payments", kwargs={"username": user.username}
        )


@pytest.mark.django_db()
class TestUserPaymentsListNav(ViewTestMixin):
    """The personal payment history sidebar flags the personal account active."""

    view = user_views.PaymentsList
    url = "/users/{username}/payments/"

    def test_personal_account_is_active(self, rf, user_factory, organization_factory):
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)

        response = self.call_view(rf, user, username=user.username)

        accounts = {
            account["organization"]: account
            for account in response.context_data["nav_accounts"]
        }
        assert accounts[user.individual_organization]["active"] is True
        assert accounts[org]["active"] is False
