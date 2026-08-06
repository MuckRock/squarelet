# Django
from django.urls import reverse

# Third Party
import factory
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.payments import views


@pytest.mark.django_db()
class TestPaymentsHubView(ViewTestMixin):
    """Test the cross-organization payments hub."""

    view = views.PaymentsHubView
    url = "/payments/"

    def test_unauthenticated_user_redirected_to_login(self, rf):
        """Anonymous users are redirected to the login page."""
        response = self.call_view(rf, user=None)

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_includes_personal_account(self, rf, user_factory):
        """The user's personal account is always the first account listed."""
        user = user_factory()

        response = self.call_view(rf, user)

        accounts = response.context_data["accounts"]
        assert accounts[0]["organization"] == user.individual_organization
        assert accounts[0]["history_url"] == reverse(
            "users:payments", kwargs={"username": user.username}
        )

    def test_includes_admin_orgs_but_not_member_orgs(
        self, rf, user_factory, organization_factory, membership_factory
    ):
        """Admin orgs appear; orgs where the user is only a member do not."""
        user = user_factory()
        admin_org = organization_factory()
        admin_org.add_creator(user)
        member_org = organization_factory()
        membership_factory(user=user, organization=member_org, admin=False)

        response = self.call_view(rf, user)

        orgs = [
            account["organization"] for account in response.context_data["accounts"]
        ]
        assert admin_org in orgs
        assert member_org not in orgs

    def test_admin_org_links_to_org_payment_history(
        self, rf, user_factory, organization_factory
    ):
        """Each admin org links out to its full org payment history."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)

        response = self.call_view(rf, user)

        account = next(
            a for a in response.context_data["accounts"] if a["organization"] == org
        )
        assert account["history_url"] == reverse(
            "organizations:payments", kwargs={"slug": org.slug}
        )

    def test_account_includes_card_and_management_urls(
        self, rf, user_factory, organization_factory
    ):
        """Each account exposes its card on file and the URLs used to
        manage the subscription and payment method."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        customer = org.customer()
        customer.payment_brand = "Visa"
        customer.payment_last4 = "4242"
        customer.save()

        response = self.call_view(rf, user)

        account = next(
            a for a in response.context_data["accounts"] if a["organization"] == org
        )
        assert account["card_brand"] == "Visa"
        assert account["card_last4"] == "4242"
        assert account["manage_url"] == reverse(
            "organizations:subscriptions", kwargs={"slug": org.slug}
        )
        assert account["update_card_url"] == reverse(
            "organizations:update-card", kwargs={"slug": org.slug}
        )

    def test_personal_account_management_urls_use_username(self, rf, user_factory):
        """The personal account's management URLs are keyed on username."""
        user = user_factory()

        response = self.call_view(rf, user)

        account = response.context_data["accounts"][0]
        assert account["organization"] == user.individual_organization
        assert account["manage_url"] == reverse(
            "users:subscriptions", kwargs={"username": user.username}
        )
        assert account["update_card_url"] == reverse(
            "users:update-card", kwargs={"username": user.username}
        )

    def test_shows_five_most_recent_payments_per_account(
        self, rf, user_factory, organization_factory, charge_factory
    ):
        """Each account shows at most its five most recent charges, newest first."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        charge_factory.create_batch(
            7, organization=org, charge_id=factory.Sequence(lambda n: f"ch_recent_{n}")
        )

        response = self.call_view(rf, user)

        account = next(
            a for a in response.context_data["accounts"] if a["organization"] == org
        )
        payments = account["payments"]
        assert len(payments) == 5
        # Newest first
        created = [p.created_at for p in payments]
        assert created == sorted(created, reverse=True)

    def test_does_not_leak_other_org_payments(
        self, rf, user_factory, organization_factory, charge_factory
    ):
        """Charges from an org the user cannot view are not shown."""
        user = user_factory()
        own_org = organization_factory()
        own_org.add_creator(user)
        other_org = organization_factory()
        charge_factory.create_batch(
            3,
            organization=other_org,
            charge_id=factory.Sequence(lambda n: f"ch_other_{n}"),
        )

        response = self.call_view(rf, user)

        orgs = [
            account["organization"] for account in response.context_data["accounts"]
        ]
        assert other_org not in orgs
