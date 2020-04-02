# Standard Library
import json
import time
from unittest.mock import Mock

# Third Party
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.organizations.choices import ChangeLogReason, StripeAccounts
from squarelet.organizations.models import Charge, Entitlement, Organization
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    InvitationFactory,
    MembershipFactory,
    OrganizationFactory,
    OrganizationPlanFactory,
    PlanFactory,
    SubscriptionFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.mark.django_db()
class TestOrganizationAPI:
    def test_retrieve(self, user_factory, mocker):
        user = user_factory(is_staff=True)
        client = APIClient()
        client.force_authenticate(user=user)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = client.get(
            f"/api/organizations/{user.individual_organization.uuid}/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert response_json["uuid"] == str(user.individual_organization.uuid)
        assert response_json["name"] == user.individual_organization.name
        assert response_json["individual"]

    def test_create_charge(self, user_factory, mocker):
        mocked = mocker.patch(
            "stripe.Charge.create",
            return_value=Mock(id="charge_id", created=time.time()),
        )
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source="default_source",
        )
        user = user_factory(is_staff=True)
        data = {
            "organization": str(user.individual_organization.uuid),
            "amount": 2700,
            "fee_amount": 5,
            "description": "This is only a test",
            "token": None,
            "save_card": False,
        }
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(f"/api/charges/", data)
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        assert "card" in response_json
        for field in ("organization", "amount", "fee_amount", "description"):
            assert response_json[field] == data[field]
        mocked.assert_called_once()
        assert Charge.objects.filter(charge_id="charge_id").exists()


@pytest.mark.django_db()
class TestPPOrganizationAPI:
    def test_list(self, api_client):
        """List organizations"""
        size = 10
        OrganizationFactory.create_batch(size)
        response = api_client.get(f"/pp-api/organizations/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size

    def test_create(self, api_client, user):
        """Create an organization"""
        api_client.force_authenticate(user=user)
        data = {"name": "Test"}
        response = api_client.post(f"/pp-api/organizations/", data)
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        organization = Organization.objects.get(uuid=response_json["uuid"])
        assert organization.has_admin(user)
        assert organization.receipt_emails.filter(email=user.email).exists()
        assert organization.change_logs.filter(reason=ChangeLogReason.created).exists()

    def test_retrieve(self, api_client, organization):
        """Test retrieving an organization"""
        response = api_client.get(f"/pp-api/organizations/{organization.uuid}/")
        assert response.status_code == status.HTTP_200_OK

    def test_update(self, api_client, user, mocker):
        """Test updating an organization"""
        mocked_modify = mocker.patch("stripe.Subscription.modify")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        organization = OrganizationFactory(admins=[user])
        SubscriptionFactory(organization=organization)
        api_client.force_authenticate(user=user)
        response = api_client.patch(
            f"/pp-api/organizations/{organization.uuid}/", {"max_users": 42}
        )
        assert response.status_code == status.HTTP_200_OK
        organization.refresh_from_db()
        assert organization.max_users == 42
        mocked_modify.assert_called_once()


@pytest.mark.django_db()
class TestPPMembershipAPI:
    def test_list(self, api_client, user):
        """List organizations"""
        size = 10
        organization = OrganizationFactory(admins=[user])
        MembershipFactory.create_batch(size, organization=organization)
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/memberships/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size + 1

    def test_retrieve(self, api_client, user):
        """Test retrieving a membership"""
        organization = OrganizationFactory(users=[user])
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/memberships/"
            f"{user.individual_organization_id}/"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_update(self, api_client, user):
        """Test updating a membership"""
        member = UserFactory()
        organization = OrganizationFactory(admins=[user], users=[member])
        api_client.force_authenticate(user=user)

        response = api_client.patch(
            f"/pp-api/organizations/{organization.uuid}/memberships/"
            f"{member.individual_organization_id}/",
            {"admin": True},
        )
        assert response.status_code == status.HTTP_200_OK
        assert organization.has_admin(member)

    def test_destroy(self, api_client, user):
        member = UserFactory()
        organization = OrganizationFactory(admins=[user], users=[member])
        api_client.force_authenticate(user=user)
        response = api_client.delete(
            f"/pp-api/organizations/{organization.uuid}/memberships/"
            f"{member.individual_organization_id}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not organization.has_member(member)


@pytest.mark.django_db()
class TestPPInvitationAPI:
    def test_list(self, api_client, user):
        """List invitations for an organization"""
        organization = OrganizationFactory(admins=[user])
        api_client.force_authenticate(user=user)
        size = 10
        InvitationFactory.create_batch(size, organization=organization)
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/invitations/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size

    def test_create_admin_invite(self, api_client, user, mailoutbox):
        """Admin invites a user to join"""
        organization = OrganizationFactory(admins=[user])
        api_client.force_authenticate(user=user)
        data = {"email": "invitee@example.org"}
        response = api_client.post(
            f"/pp-api/organizations/{organization.uuid}/invitations/", data
        )
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        assert not response_json["request"]
        assert response_json["user"] is None
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == f"Invitation to join {organization.name}"
        assert mail.to == [data["email"]]

    def test_create_user_request(self, api_client, user, mailoutbox):
        """User requests to join an organization"""
        admin = UserFactory()
        organization = OrganizationFactory(admins=[admin])
        api_client.force_authenticate(user=user)
        response = api_client.post(
            f"/pp-api/organizations/{organization.uuid}/invitations/"
        )
        assert response.status_code == status.HTTP_201_CREATED
        invitation = organization.invitations.first()
        assert invitation.request
        assert invitation.user == user
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == f"{user} has requested to join {organization}"
        assert mail.to == [admin.email]

    def test_retrieve(self, api_client, invitation):
        """Get an invitation"""
        response = api_client.get(f"/pp-api/invitations/{invitation.uuid}/")
        assert response.status_code == status.HTTP_200_OK

    def test_update(self, api_client, user, invitation):
        """Accept an invitation"""
        api_client.force_authenticate(user=user)
        response = api_client.patch(
            f"/pp-api/invitations/{invitation.uuid}/", {"accept": True}
        )
        assert response.status_code == status.HTTP_200_OK
        invitation.refresh_from_db()
        assert invitation.accepted_at
        assert invitation.organization.has_member(user)

    def test_retrieve_expand_org(self, api_client, invitation):
        """Get an invitation with expanded organization data"""
        response = api_client.get(
            f"/pp-api/invitations/{invitation.uuid}/?expand=organization"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert "name" in response_json["organization"]


@pytest.mark.django_db()
class TestPPPlanAPI:
    def test_list(self, api_client):
        """List plans"""
        size = 10
        PlanFactory.create_batch(size)
        response = api_client.get(f"/pp-api/plans/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size
        assert "id" in response_json["results"][0]

    def test_list_filter_by_account(self, api_client):
        """List plans by stripe account"""
        size = 2
        PlanFactory.create_batch(size, stripe_account=StripeAccounts.muckrock)
        PlanFactory.create_batch(size, stripe_account=StripeAccounts.presspass)

        for account in [StripeAccounts.muckrock, StripeAccounts.presspass]:
            response = api_client.get(f"/pp-api/plans/", {"account": account})
            assert response.status_code == status.HTTP_200_OK
            response_json = json.loads(response.content)
            assert len(response_json["results"]) == size

        response = api_client.get(f"/pp-api/plans/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == 2 * size

    def test_list_filter_by_organization(self, api_client, user):
        """List plans for a given organization"""
        api_client.force_authenticate(user=user)
        org = OrganizationFactory(admins=[user])
        ind_plan = PlanFactory(for_individuals=True, for_groups=False, public=True)
        grp_plan = PlanFactory(for_individuals=False, for_groups=True, public=True)
        priv_plan = PlanFactory(for_individuals=False, for_groups=True, public=False)
        my_plan = PlanFactory(for_individuals=False, for_groups=True, public=False)
        my_plan.private_organizations.add(org)

        response = api_client.get(f"/pp-api/plans/", {"organization": org.uuid})
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        # you should not be able to see the individual plan or the private plan
        # which is not shared with you
        plan_ids = [j["id"] for j in response_json["results"]]
        assert ind_plan.pk not in plan_ids
        assert grp_plan.pk in plan_ids
        assert priv_plan.pk not in plan_ids
        assert my_plan.pk in plan_ids

    def test_list_filter_by_organization_bad(self, api_client, organization):
        """You may not list plans for an organization you are not a member of"""
        response = api_client.get(
            f"/pp-api/plans/", {"organization": organization.uuid}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrieve(self, api_client, mocker):
        """Test retrieving a plan"""
        mocker.patch("stripe.Plan.create")
        plan = PlanFactory()
        response = api_client.get(f"/pp-api/plans/{plan.id}/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert "id" in response_json


@pytest.mark.django_db()
class TestPPEntitlementAPI:
    def test_list(self, api_client, user):
        """List entitlements"""
        size = 10
        entitlements = EntitlementFactory.create_batch(size)
        plan = PlanFactory(public=True)
        plan.entitlements.set(entitlements)
        response = api_client.get(f"/pp-api/entitlements/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size

    def test_subscribed(self, api_client, user):
        """List entitlements for a subscribed user"""
        size = 10
        api_client.force_authenticate(user=user)
        org = OrganizationFactory(admins=[user])
        plan = PlanFactory(for_individuals=False, for_groups=True, public=False)
        plan.private_organizations.add(org)
        entitlements = EntitlementFactory.create_batch(size)
        plan.entitlements.set(entitlements)
        SubscriptionFactory(plan=plan, organization=org)
        response = api_client.get(f"/pp-api/entitlements/?subscribed=true")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size

    def test_list_expand_clients(self, api_client, mocker):
        """List entitlements"""
        size = 10
        entitlements = EntitlementFactory.create_batch(size)
        mocker.patch("stripe.Plan.create")
        # make entitlements public by adding it to a public plan
        plan = PlanFactory(public=True)
        plan.entitlements.set(entitlements)
        response = api_client.get(f"/pp-api/entitlements/?expand=client")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size
        for entitlement in response_json["results"]:
            assert "name" in entitlement["client"]

    def test_create(self, api_client, client):
        """Create an entitlement"""
        api_client.force_authenticate(user=client.owner)
        data = {
            "name": "Test Entitlement",
            "client": client.pk,
            "description": "Description goes here",
        }
        response = api_client.post(f"/pp-api/entitlements/", data)
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_bad(self, api_client, user, client):
        """Create an entitlement for a client you don't own"""
        api_client.force_authenticate(user=user)
        data = {
            "name": "Test Entitlement",
            "client": client.pk,
            "description": "Description goes here",
        }
        response = api_client.post(f"/pp-api/entitlements/", data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrieve(self, api_client, entitlement, mocker):
        """Test retrieving an entitlement"""
        mocker.patch("stripe.Plan.create")
        # make entitlement public by adding it to a public plan
        plan = PlanFactory(public=True)
        plan.entitlements.add(entitlement)
        response = api_client.get(f"/pp-api/entitlements/{entitlement.pk}/")
        assert response.status_code == status.HTTP_200_OK

    def test_retrieve_expand_client(self, api_client, entitlement, mocker):
        """Test retrieving an entitlement"""
        mocker.patch("stripe.Plan.create")
        # make entitlement public by adding it to a public plan
        plan = PlanFactory(public=True)
        plan.entitlements.add(entitlement)
        response = api_client.get(
            f"/pp-api/entitlements/{entitlement.pk}/?expand=client"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert "name" in response_json["client"]

    def test_retrieve_bad(self, api_client, entitlement):
        """Test retrieving a private entitlement"""
        response = api_client.get(f"/pp-api/entitlements/{entitlement.pk}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update(self, api_client, entitlement):
        """Test updating an entitlement"""
        api_client.force_authenticate(user=entitlement.client.owner)
        data = {"description": "new description"}
        response = api_client.patch(f"/pp-api/entitlements/{entitlement.pk}/", data)
        assert response.status_code == status.HTTP_200_OK
        entitlement.refresh_from_db()
        assert entitlement.description == data["description"]

    def test_destroy(self, api_client, entitlement):
        api_client.force_authenticate(user=entitlement.client.owner)
        response = api_client.delete(f"/pp-api/entitlements/{entitlement.pk}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Entitlement.objects.filter(pk=entitlement.pk).exists()


@pytest.mark.django_db()
class TestPPSubscriptionAPI:
    def test_list(self, api_client, user):
        """List subscriptions"""
        size = 10
        organization = OrganizationFactory(admins=[user])
        api_client.force_authenticate(user=user)
        SubscriptionFactory.create_batch(size, organization=organization)
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/subscriptions/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size
        assert "id" in response_json["results"][0]

    def test_list_expand_plans(self, api_client, user):
        """List subscriptions expanding plans"""
        size = 10
        organization = OrganizationFactory(admins=[user])
        api_client.force_authenticate(user=user)
        SubscriptionFactory.create_batch(size, organization=organization)
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/subscriptions/?expand=plan"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size
        assert "name" in response_json["results"][0]["plan"]

    def test_create(self, api_client, user, mocker):
        """Create a subscription"""
        mocker.patch("stripe.Plan.create")
        stripe_id = "stripe_subscription_id"
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email=None,
            **{"subscriptions.create.return_value": Mock(id=stripe_id)},
        )
        plan = OrganizationPlanFactory()
        organization = OrganizationFactory(admins=[user])
        api_client.force_authenticate(user=user)
        data = {"plan": plan.pk, "token": "stripe_token"}
        response = api_client.post(
            f"/pp-api/organizations/{organization.uuid}/subscriptions/", data
        )
        assert response.status_code == status.HTTP_201_CREATED
        mocked_customer.subscriptions.create.assert_called_with(
            items=[{"plan": plan.stripe_id, "quantity": organization.max_users}],
            billing="charge_automatically",
            days_until_due=None,
        )
        assert mocked_customer.email == organization.email
        assert mocked_customer.source == "stripe_token"
        assert mocked_customer.save.call_count == 2
        assert organization.subscriptions.first().subscription_id == stripe_id

    def test_retrieve(self, api_client, user, mocker):
        """Test retrieving a subscription"""
        mocker.patch("stripe.Plan.create")
        organization = OrganizationFactory(admins=[user])
        subscription = SubscriptionFactory(organization=organization)
        api_client.force_authenticate(user=user)
        response = api_client.get(
            f"/pp-api/organizations/{organization.uuid}/subscriptions/"
            f"{subscription.pk}/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert "id" in response_json

    def test_destroy(self, api_client, user, mocker):
        """Test cancelling a subscription"""
        mocker.patch("stripe.Plan.create")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        organization = OrganizationFactory(admins=[user])
        subscription = SubscriptionFactory(organization=organization)
        api_client.force_authenticate(user=user)
        response = api_client.delete(
            f"/pp-api/organizations/{organization.uuid}/subscriptions/"
            f"{subscription.pk}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        subscription.refresh_from_db()
        assert subscription.cancelled
        assert mocked_stripe_subscription.cancel_at_period_end is True
        mocked_stripe_subscription.save.assert_called_once()


@pytest.mark.django_db()
class TestPPUserMembershipAPI:
    def test_list(self, api_client, user):
        """List user memberships"""
        api_client.force_authenticate(user=user)
        organization = OrganizationFactory(admins=[user], private=True)
        new_user = UserFactory()
        MembershipFactory(organization=organization, user=new_user, admin=False)
        response = api_client.get(
            f"/pp-api/users/{new_user.individual_organization_id}/memberships/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == 1
