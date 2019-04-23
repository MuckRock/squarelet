# Django
from django.utils import timezone

# Standard Library
from datetime import date
from unittest.mock import Mock, PropertyMock

# Third Party
import pytest
from dateutil.relativedelta import relativedelta

# Squarelet
from squarelet.organizations.models import ReceiptEmail


# pylint: disable=invalid-name,too-many-public-methods,protected-access


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

    def test_email_individual(self, user_factory):
        user = user_factory.build()
        assert user.individual_organization.email == user.email

    @pytest.mark.django_db()
    def test_email_receipt(self, organization_factory):
        organization = organization_factory()
        email = "org@example.com"
        organization.receipt_emails.create(email=email)
        assert organization.email == email

    @pytest.mark.django_db()
    def test_email_admin(self, organization_factory, user_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        assert organization.email == user.email

    @pytest.mark.django_db()
    def test_has_admin(self, organization_factory, user_factory):
        admin, member, user = user_factory.create_batch(3)
        org = organization_factory(users=[member], admins=[admin])

        assert org.has_admin(admin)
        assert not org.has_admin(member)
        assert not org.has_admin(user)

    @pytest.mark.django_db()
    def test_has_member(self, organization_factory, user_factory):
        admin, member, user = user_factory.create_batch(3)
        org = organization_factory(users=[member], admins=[admin])

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

    def test_customer_existing(self, organization_factory, mocker):
        mocked = mocker.patch("stripe.Customer.retrieve")
        customer_id = "customer_id"
        organization = organization_factory.build(customer_id=customer_id)
        assert mocked.return_value == organization.customer
        mocked.assert_called_with(customer_id)

    def test_customer_new(self, organization_factory, mocker):
        customer_id = "customer_id"
        customer = Mock(id=customer_id)
        mocked_create = mocker.patch("stripe.Customer.create", return_value=customer)
        mocked_save = mocker.patch("squarelet.organizations.models.Organization.save")
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        organization = organization_factory.build()
        assert customer == organization.customer
        mocked_create.assert_called_with(description=organization.name, email=email)
        mocked_save.assert_called_once()

    def test_subscription_existing(self, organization_factory, mocker):
        mocked = mocker.patch("stripe.Subscription.retrieve")
        subscription_id = "subscription_id"
        organization = organization_factory.build(subscription_id=subscription_id)
        assert mocked.return_value == organization.subscription
        mocked.assert_called_with(subscription_id)

    def test_subscription_blank(self, organization_factory):
        organization = organization_factory.build()
        assert organization.subscription is None

    def test_card_existing(self, organization_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "card"
        organization = organization_factory.build()
        assert mocked.sources.retrieve.return_value == organization.card
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_ach(self, organization_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "ach"
        organization = organization_factory.build()
        assert organization.card is None
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_blank(self, organization_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Organization.customer", default_source=None
        )
        organization = organization_factory.build()
        assert organization.card is None

    def test_card_display(self, organization_factory, mocker):
        brand = "Visa"
        last4 = "4242"
        mocker.patch(
            "squarelet.organizations.models.Organization.card", brand=brand, last4=last4
        )
        organization = organization_factory.build(customer_id="customer_id")
        assert organization.card_display == f"{brand}: {last4}"

    def test_card_display_empty(self, organization_factory):
        organization = organization_factory.build()
        assert organization.card_display == ""

    def test_save_card(self, organization_factory, mocker):
        token = "token"
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Organization.customer"
        )
        mocked_save = mocker.patch("squarelet.organizations.models.Organization.save")
        mocked_sci = mocker.patch(
            "squarelet.organizations.models.send_cache_invalidations"
        )
        organization = organization_factory.build()
        organization.save_card(token)
        assert not organization.payment_failed
        mocked_save.assert_called_once()
        assert mocked_customer.source == token
        mocked_customer.save.assert_called_once()
        mocked_sci.assert_called_with("organization", organization.uuid)

    def test_set_subscription_create(
        self, organization_factory, organization_plan_factory, mocker
    ):
        organization = organization_factory.build()
        organization_plan = organization_plan_factory.build()
        mocked_create = mocker.patch(
            "squarelet.organizations.models.Organization._create_subscription"
        )
        mocked_save_card = mocker.patch(
            "squarelet.organizations.models.Organization.save_card"
        )
        mocker.patch("squarelet.organizations.models.Organization.customer")
        token = "token"
        max_users = 10
        organization.set_subscription(token, organization_plan, max_users)
        mocked_save_card.assert_called_with(token)
        mocked_create.assert_called_with(
            organization.customer, organization_plan, max_users
        )

    def test_set_subscription_cancel(
        self, organization_factory, free_plan_factory, organization_plan_factory, mocker
    ):
        organization = organization_factory.build(
            plan=organization_plan_factory.build()
        )
        free_plan = free_plan_factory.build()
        mocked_cancel = mocker.patch(
            "squarelet.organizations.models.Organization._cancel_subscription"
        )
        max_users = 5
        organization.set_subscription(None, free_plan, max_users)
        mocked_cancel.assert_called_with(free_plan)

    def test_set_subscription_modify(
        self, individual_organization_factory, professional_plan_factory, mocker
    ):
        professional_plan = professional_plan_factory.build()
        organization = individual_organization_factory.build(plan=professional_plan)
        mocked_modify = mocker.patch(
            "squarelet.organizations.models.Organization._modify_subscription"
        )
        mocker.patch("squarelet.organizations.models.Organization.customer")
        max_users = 10
        organization.set_subscription(None, professional_plan, max_users)
        # individual orgs always have 1 user
        mocked_modify.assert_called_with(organization.customer, professional_plan, 1)

    def test_set_subscription_modify_free(self, organization_factory, mocker):
        organization = organization_factory.build()
        mocked_modify = mocker.patch(
            "squarelet.organizations.models.Organization._modify_plan"
        )
        max_users = 10
        organization.set_subscription(None, organization.plan, max_users)
        mocked_modify.assert_called_with(organization.plan, max_users)

    @pytest.mark.django_db(transaction=True)
    def test_create_subscription(
        self, organization_factory, organization_plan_factory, mocker
    ):
        organization = organization_factory()
        organization_plan = organization_plan_factory()
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        subscription_id = "subscription_id"
        mocked.subscriptions.create.return_value.id = subscription_id
        max_users = 10
        organization._create_subscription(
            organization.customer, organization_plan, max_users
        )
        assert organization.plan == organization_plan
        assert organization.next_plan == organization_plan
        assert organization.max_users == max_users
        assert organization.update_on == date.today() + relativedelta(months=1)
        mocked.subscriptions.create.assert_called_with(
            items=[{"plan": organization_plan.stripe_id, "quantity": max_users}],
            billing="charge_automatically",
            days_until_due=None,
        )
        assert organization.subscription_id == subscription_id

    def test_cancel_subscription(
        self, organization_factory, organization_plan_factory, free_plan_factory, mocker
    ):
        organization_plan = organization_plan_factory.build()
        organization = organization_factory.build(
            plan=organization_plan,
            next_plan=organization_plan,
            subscription_id="subscription_id",
        )
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        mocked_save = mocker.patch("squarelet.organizations.models.Organization.save")
        free_plan = free_plan_factory.build()
        organization._cancel_subscription(free_plan)
        assert mocked_subscription.cancel_at_period_end is True
        mocked_subscription.save.assert_called_once()
        assert organization.subscription_id is None
        assert organization.next_plan == free_plan
        mocked_save.assert_called_once()

    def test_modify_subscription(
        self, organization_factory, organization_plan_factory, mocker
    ):
        organization_plan = organization_plan_factory.build()
        organization = organization_factory.build(
            plan=organization_plan,
            next_plan=organization_plan,
            subscription_id="subscription_id",
        )
        mocker.patch("squarelet.organizations.models.Organization.customer")
        mocked_stripe = mocker.patch("squarelet.organizations.models.stripe")
        mocked_modify_plan = mocker.patch(
            "squarelet.organizations.models.Organization._modify_plan"
        )
        max_users = 10
        organization._modify_subscription(
            organization.customer, organization_plan, max_users
        )

        mocked_stripe.Subscription.modify.assert_called_with(
            organization.subscription_id,
            cancel_at_period_end=False,
            items=[
                {
                    "id": organization.subscription["items"]["data"][0].id,
                    "plan": organization_plan.stripe_id,
                    "quantity": max_users,
                }
            ],
            billing="charge_automatically",
            days_until_due=None,
        )
        mocked_modify_plan.assert_called_with(organization_plan, max_users)

    def test_modify_plan_upgrade(
        self, organization_factory, organization_plan_factory, free_plan_factory, mocker
    ):
        organization_plan = organization_plan_factory.build()
        free_plan = free_plan_factory.build()
        organization = organization_factory.build(plan=free_plan, next_plan=free_plan)
        mocked_save = mocker.patch("squarelet.organizations.models.Organization.save")
        max_users = 10
        organization._modify_plan(organization_plan, max_users)

        assert organization.plan == organization_plan
        assert organization.next_plan == organization_plan
        assert organization.max_users == max_users
        mocked_save.assert_called_once()

    def test_modify_plan_downgrade(
        self, organization_factory, organization_plan_factory, free_plan_factory, mocker
    ):
        organization_plan = organization_plan_factory.build()
        free_plan = free_plan_factory.build()
        organization = organization_factory.build(
            plan=organization_plan, next_plan=organization_plan
        )
        mocked_save = mocker.patch("squarelet.organizations.models.Organization.save")
        max_users = 10
        organization._modify_plan(free_plan, max_users)

        assert organization.plan == organization_plan
        assert organization.next_plan == free_plan
        assert organization.max_users == max_users
        mocked_save.assert_called_once()

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

    def test_make_stripe_plan_individual(self, professional_plan_factory, mocker):
        mocked = mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory.build()
        plan.make_stripe_plan()
        mocked.assert_called_with(
            id=plan.stripe_id,
            currency="usd",
            interval="month",
            product={"name": plan.name, "unit_label": "Seats"},
            billing_scheme="per_unit",
            amount=100 * plan.base_price,
        )

    def test_make_stripe_plan_group(self, organization_plan_factory, mocker):
        mocked = mocker.patch("stripe.Plan.create")
        plan = organization_plan_factory.build()
        plan.make_stripe_plan()
        mocked.assert_called_with(
            id=plan.stripe_id,
            currency="usd",
            interval="month",
            product={"name": plan.name, "unit_label": "Seats"},
            billing_scheme="tiered",
            tiers=[
                {"flat_amount": 100 * plan.base_price, "up_to": plan.minimum_users},
                {"unit_amount": 100 * plan.price_per_user, "up_to": "inf"},
            ],
            tiers_mode="graduated",
        )


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
    def test_accept_duplicate(self, invitation, user_factory, membership_factory):
        invitation.user = user_factory()
        membership_factory(organization=invitation.organization, user=invitation.user)
        assert invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

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
        assert set(mail.to) == set(emails)

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
