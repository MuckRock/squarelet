# Django
from django.utils import timezone

# Standard Library
from unittest.mock import PropertyMock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import ReceiptEmail

# pylint: disable=invalid-name


class TestOrganization:
    """Unit tests for Organization model"""

    def test_str(self, organization_factory):
        organization = organization_factory.build()
        assert str(organization) == organization.name

    def test_str_individual(self, individual_organization_factory):
        organization = individual_organization_factory.build()
        assert str(organization) == f"{organization.name} (Individual)"

    @pytest.mark.django_db(transaction=True)
    def test_save(self, organization_factory, mocker):
        mocked = mocker.patch("squarelet.organizations.models.send_cache_invalidations")
        organization = organization_factory()
        mocked.assert_called_with("organization", organization.uuid)

    def test_get_absolute_url(self, organization_factory):
        organization = organization_factory.build()
        assert organization.get_absolute_url() == f"/organizations/{organization.slug}/"

    def test_get_absolute_url_individual(self, user_factory):
        user = user_factory.build()
        assert (
            user.individual_organization.get_absolute_url() == user.get_absolute_url()
        )

    @pytest.mark.django_db()
    def test_has_admin(self, organization_factory, user_factory, membership_factory):
        admin, member, user = user_factory.create_batch(3)
        org = organization_factory()
        membership_factory(user=admin, organization=org, admin=True)
        membership_factory(user=member, organization=org, admin=False)

        assert org.has_admin(admin)
        assert not org.has_admin(member)
        assert not org.has_admin(user)

    @pytest.mark.django_db()
    def test_has_member(self, organization_factory, user_factory, membership_factory):
        admin, member, user = user_factory.create_batch(3)
        org = organization_factory()
        membership_factory(user=admin, organization=org, admin=True)
        membership_factory(user=member, organization=org, admin=False)

        assert org.has_member(admin)
        assert org.has_member(member)
        assert not org.has_member(user)

    @pytest.mark.django_db()
    def test_user_count(
        self, organization_factory, membership_factory, invitation_factory
    ):
        org = organization_factory()
        membership_factory.create_batch(4, organization=org)
        invitation_factory.create_batch(3, organization=org, request=True)
        invitation_factory.create_batch(2, organization=org, request=False)

        # current users and pending invitations count - requested invitations
        # do not count
        assert org.user_count() == 6

    @pytest.mark.django_db()
    def test_add_creator(self, organization_factory, user_factory):
        org = organization_factory()
        user = user_factory()

        org.add_creator(user)

        # add creator makes the user an admin and adds their email address as a receipt
        # email

        assert org.has_admin(user)
        assert org.receipt_emails.first().email == user.email

    def test_reference_name(self, organization_factory):
        organization = organization_factory.build()
        assert organization.reference_name == organization.name

    def test_reference_name_individual(self, individual_organization_factory):
        organization = individual_organization_factory.build()
        assert organization.reference_name == "Your account"

    @pytest.mark.django_db()
    def test_set_receipt_emails(self, organization_factory):
        organization = organization_factory()

        assert not organization.receipt_emails.all()

        emails = ["email1@example.com", "email2@example.com", "email3@example.com"]
        organization.set_receipt_emails(emails)
        assert set(emails) == set(r.email for r in organization.receipt_emails.all())

        emails = ["email2@example.com", "email4@example.com"]
        organization.set_receipt_emails(emails)
        assert set(emails) == set(r.email for r in organization.receipt_emails.all())


class TestMembership:
    """Unit tests for Membership model"""

    def test_str(self, membership_factory):
        membership = membership_factory.build()
        assert (
            str(membership)
            == f"Membership: {membership.user} in {membership.organization}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_save(self, membership_factory, mocker):
        mocked = mocker.patch("squarelet.organizations.models.send_cache_invalidations")
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)

    @pytest.mark.django_db(transaction=True)
    def test_save_delete(self, membership_factory, mocker):
        mocked = mocker.patch("squarelet.organizations.models.send_cache_invalidations")
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)
        mocked.reset_mock()
        membership.delete()
        mocked.assert_called_with("user", membership.user.uuid)


class TestPlan:
    """Unit tests for Organization model"""

    def test_str(self, free_plan_factory):
        plan = free_plan_factory.build()
        assert str(plan) == "Free"

    def test_free(self, free_plan_factory):
        plan = free_plan_factory.build()
        assert plan.free()

    def test_not_free(self, professional_plan_factory):
        plan = professional_plan_factory.build()
        assert not plan.free()

    @pytest.mark.parametrize(
        "users,cost", [(0, 100), (1, 100), (5, 100), (7, 120), (10, 150)]
    )
    def test_cost(self, organization_plan_factory, users, cost):
        plan = organization_plan_factory.build()
        assert plan.cost(users) == cost

    def test_stripe_id(self, free_plan_factory):
        plan = free_plan_factory.build()
        assert plan.stripe_id == "squarelet_plan_free"


class TestInvitation:
    """Unit tests for Invitation model"""

    def test_str(self, invitation_factory):
        invitation = invitation_factory.build()
        assert str(invitation) == f"Invitation: {invitation.uuid}"

    def test_send(self, invitation_factory, mailoutbox):
        invitation = invitation_factory.build()
        invitation.send()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == f"Invitation to join {invitation.organization.name}"
        assert mail.to == [invitation.email]

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_with_user(self, invitation, user_factory):
        invitation.user = user_factory()
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_without_user(self, invitation, user_factory):
        user = user_factory()
        assert invitation.user is None
        invitation.accept(user)
        assert invitation.user == user
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.django_db()
    def test_accept_missing_user(self, invitation_factory):
        invitation = invitation_factory.build()
        assert invitation.user is None
        with pytest.raises(ValueError):
            invitation.accept()

    @pytest.mark.django_db()
    def test_accept_closed(self, invitation_factory, user_factory):
        user = user_factory.build()
        invitation = invitation_factory.build(accepted_at=timezone.now())
        with pytest.raises(ValueError):
            invitation.accept(user)

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_reject(self, invitation):
        invitation.reject()
        assert invitation.rejected_at == timezone.now()

    def test_reject_closed(self, invitation_factory):
        invitation = invitation_factory.build(rejected_at=timezone.now())
        with pytest.raises(ValueError):
            invitation.reject()

    def test_get_name_no_user(self, invitation_factory):
        invitation = invitation_factory.build()
        assert invitation.get_name() == invitation.email

    def test_get_name_user(self, invitation_factory, user_factory):
        invitation = invitation_factory.build()
        invitation.user = user_factory.build()
        assert invitation.get_name() == invitation.user.name


class TestReceiptEmail:
    """Unit tests for ReceiptEmail model"""

    def test_str(self):
        receipt_email = ReceiptEmail(email="email@example.com")
        assert str(receipt_email) == f"Receipt Email: <{receipt_email.email}>"


class TestCharge:
    """Unit tests for Charge model"""

    def test_str(self, charge_factory):
        charge = charge_factory.build()
        assert (
            str(charge)
            == f"${charge.amount / 100:.2f} charge to {charge.organization.name}"
        )

    def test_get_absolute_url(self, charge_factory):
        charge = charge_factory.build(pk=1)
        assert charge.get_absolute_url() == f"/organizations/~charge/{charge.pk}/"

    def test_amount_dollars(self, charge_factory):
        charge = charge_factory.build(amount=350)
        assert charge.amount_dollars == 3.50

    @pytest.mark.django_db()
    def test_send_receipt(self, charge_factory, mailoutbox, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.Charge.charge", new_callable=PropertyMock
        )
        mocked.return_value = {"source": {"brand": "Visa", "last4": "1234"}}

        emails = ["receipts@example.com", "foo@example.com"]
        charge = charge_factory()
        charge.organization.set_receipt_emails(emails)
        charge.send_receipt()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == "Receipt"
        assert mail.to == emails

    def test_items_no_fee(self, charge_factory):
        charge = charge_factory.build()
        assert charge.items() == [
            {"name": charge.description, "price": charge.amount_dollars}
        ]

    def test_items_fee(self, charge_factory):
        charge = charge_factory.build(amount=10500, fee_amount=5)
        assert charge.items() == [
            {"name": charge.description, "price": 100.00},
            {"name": "Processing Fee", "price": 5.00},
        ]
