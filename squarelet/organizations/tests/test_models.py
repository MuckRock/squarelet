# Django
from django.utils import timezone

# Standard Library
from unittest.mock import Mock, PropertyMock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import ReceiptEmail
from squarelet.organizations.tests.factories import EntitlementFactory, PlanFactory

# pylint: disable=too-many-public-methods


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
        mocked = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )
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

    @pytest.mark.django_db()
    def test_customer_existing(self, customer_factory):
        customer_id = "customer_id"
        customer = customer_factory(customer_id=customer_id)
        assert customer == customer.organization.customer()

    @pytest.mark.django_db()
    def test_customer_new(self, organization_factory, mocker):
        customer_id = "customer_id"
        stripe_customer = Mock(id=customer_id)
        mocked_stripe_create = mocker.patch(
            "stripe.Customer.create", return_value=stripe_customer
        )
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        organization = organization_factory(customer=None)
        customer = organization.customer()
        assert customer.stripe_customer
        customer.refresh_from_db()
        assert customer.customer_id == customer_id
        assert customer.organization == organization
        mocked_stripe_create.assert_called_with(
            description=organization.name,
            email=email,
            name=organization.user_full_name,
        )

    @pytest.mark.django_db()
    def test_subscription_blank(self, organization_factory):
        organization = organization_factory()
        assert organization.subscription is None

    def test_save_card(self, organization_factory, mocker):
        token = "token"
        customer = Mock()
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=customer,
        )
        mocked_save = mocker.patch(
            "squarelet.organizations.models.organization.Organization.save"
        )
        mocked_sci = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )
        organization = organization_factory.build()
        organization.save_card(token)
        assert not organization.payment_failed
        mocked_save.assert_called_once()
        customer.save_card.assert_called_with(token)
        mocked_sci.assert_called_with("organization", organization.uuid)

    @pytest.mark.django_db
    def test_set_subscription_modify_free(
        self, organization_factory, mocker, user_factory
    ):
        user = user_factory()
        organization = organization_factory()
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        organization.set_subscription(None, organization.plan, max_users, user)
        organization.refresh_from_db()
        assert organization.max_users == 10

    @pytest.mark.django_db
    def test_create_subscription(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()
        mocked_save_card = mocker.patch(
            "squarelet.organizations.models.Organization.save_card"
        )
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer", email=None
        )
        mocked_subscriptions = mocker.patch(
            "squarelet.organizations.models.Organization.subscriptions"
        )
        token = "token"
        organization.create_subscription(token, plan)
        mocked_save_card.assert_called_with(token)
        assert mocked_customer.email == organization.email
        mocked_customer.save.assert_called()
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan
        )

    @pytest.mark.django_db
    def test_set_subscription_create(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()
        mocked = mocker.patch(
            "squarelet.organizations.models.Organization.create_subscription"
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        mocker.patch("squarelet.organizations.models.Organization.save_card")
        max_users = 10
        token = "token"
        organization.set_subscription(token, plan, max_users, user)
        mocked.assert_called_with(token, plan)

    @pytest.mark.django_db
    def test_set_subscription_cancel(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        plan = professional_plan_factory()
        organization = organization_factory(admins=[user], plans=[plan])
        mocked = mocker.patch("squarelet.organizations.models.Subscription.cancel")
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        token = None
        organization.set_subscription(token, None, max_users, user)
        mocked.assert_called()

    @pytest.mark.django_db
    def test_set_subscription_modify(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        plan = professional_plan_factory()
        organization = organization_factory(admins=[user], plans=[plan])
        mocked = mocker.patch("squarelet.organizations.models.Subscription.modify")
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        token = None
        organization.set_subscription(token, plan, max_users, user)
        mocked.assert_called_with(plan)

    @pytest.mark.django_db
    def test_subscription_cancelled(
        self, organization_factory, mocker, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory(plans=[plan])
        mocked_change_logs = mocker.patch(
            "squarelet.organizations.models.Organization.change_logs"
        )
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        organization.subscription_cancelled()
        mocked_change_logs.create.assert_called_with(
            reason=ChangeLogReason.failed,
            from_plan=plan,
            from_max_users=organization.max_users,
            to_max_users=organization.max_users,
        )
        mocked_subscription.delete.assert_called()

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


class TestCustomer:
    """Unit tests for Customer model"""

    def test_customer_existing(self, customer_factory, mocker):
        mocked = mocker.patch("stripe.Customer.retrieve")
        customer_id = "customer_id"
        customer = customer_factory.build(customer_id=customer_id)
        assert mocked.return_value == customer.stripe_customer
        mocked.assert_called_with(customer_id)

    @pytest.mark.django_db()
    def test_customer_new(self, customer_factory, mocker):
        customer_id = "customer_id"
        mock_customer = Mock(id=customer_id)
        mocked_create = mocker.patch(
            "stripe.Customer.create", return_value=mock_customer
        )
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        customer = customer_factory(customer_id=None)
        assert mock_customer == customer.stripe_customer
        mocked_create.assert_called_with(
            description=customer.organization.name,
            email=email,
            name=customer.organization.user_full_name,
        )
        customer.refresh_from_db()
        assert customer.customer_id == customer_id

    def test_card_existing(self, customer_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "card"
        customer = customer_factory.build()
        assert mocked.sources.retrieve.return_value == customer.card
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_ach(self, customer_factory, mocker):
        default_source = "default_source"
        mocked = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=default_source,
        )
        mocked.sources.retrieve.return_value.object = "ach"
        customer = customer_factory.build()
        assert customer.card is None
        mocked.sources.retrieve.assert_called_with(default_source)

    def test_card_blank(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        customer = customer_factory.build()
        assert customer.card is None

    def test_card_display(self, customer_factory, mocker):
        brand = "Visa"
        last4 = "4242"
        mocker.patch(
            "squarelet.organizations.models.Customer.card", brand=brand, last4=last4
        )
        customer = customer_factory.build(customer_id="customer_id")
        assert customer.card_display == f"{brand}: {last4}"

    def test_card_display_empty(self, customer_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        customer = customer_factory.build()
        assert customer.card_display == ""

    def test_save_card(self, customer_factory, mocker):
        token = "token"
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer"
        )
        customer = customer_factory.build()
        customer.save_card(token)
        assert mocked_customer.source == token
        mocked_customer.save.assert_called_once()


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
        mocked = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)

    @pytest.mark.django_db(transaction=True)
    def test_save_delete(self, membership_factory, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)
        mocked.reset_mock()
        membership.delete()
        mocked.assert_called_with("user", membership.user.uuid)


class TestSubscription:
    """Unit tests for the Subscription model"""

    def test_str(self, subscription_factory):
        subscription = subscription_factory.build()
        assert (
            str(subscription)
            == f"Subscription: {subscription.organization} to {subscription.plan.name}"
        )

    def test_stripe_subscription(self, subscription_factory, mocker):
        mocked = mocker.patch("stripe.Subscription.retrieve")
        stripe_subscription = "stripe_subscription"
        mocked.return_value = stripe_subscription
        subscription_id = "subscription_id"
        subscription = subscription_factory.build(subscription_id=subscription_id)
        assert subscription.stripe_subscription == stripe_subscription

    def test_stripe_subscription_empty(self, subscription_factory):
        subscription = subscription_factory.build()
        assert subscription.stripe_subscription is None

    def test_start(self, subscription_factory, professional_plan_factory, mocker):
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build(plan=plan)
        mocked = Mock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked,
        )
        subscription.start()
        mocked.stripe_customer.subscriptions.create.assert_called_with(
            items=[
                {
                    "plan": subscription.plan.stripe_id,
                    "quantity": subscription.organization.max_users,
                }
            ],
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
        )
        assert (
            subscription.subscription_id
            == mocked.stripe_customer.subscriptions.create.return_value.id
        )

    def test_start_existing(self, subscription_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_factory.build()
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        subscription.start()
        mocked.subscriptions.create.assert_not_called()

    def test_start_free(self, subscription_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_factory.build()
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        subscription.start()
        mocked.subscriptions.create.assert_not_called()

    def test_cancel(self, subscription_factory, mocker):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        subscription = subscription_factory.build()
        subscription.cancel()
        assert mocked_stripe_subscription.cancel_at_period_end
        mocked_stripe_subscription.save.assert_called()
        assert subscription.cancelled
        mocked_save.assert_called()

    def test_modify_start(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_start = mocker.patch("squarelet.organizations.models.Subscription.start")
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build()
        subscription.modify(plan)
        mocked_save.assert_called()
        mocked_start.assert_called()

    def test_modify_cancel(
        self, subscription_factory, professional_plan_factory, plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        plan = professional_plan_factory.build()
        free_plan = plan_factory.build()
        subscription = subscription_factory.build(plan=plan, subscription_id="id")
        subscription.modify(free_plan)
        mocked_save.assert_called()
        mocked_stripe_subscription.delete.assert_called()
        assert subscription.subscription_id is None

    def test_modify_modify(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_modify = mocker.patch("stripe.Subscription.modify")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build(plan=plan)
        subscription.modify(plan)
        mocked_save.assert_called()
        mocked_modify.assert_called_with(
            subscription.subscription_id,
            cancel_at_period_end=False,
            items=[
                {
                    "id": subscription.stripe_subscription["items"]["data"][0].id,
                    "plan": subscription.plan.stripe_id,
                    "quantity": subscription.organization.max_users,
                }
            ],
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
        )


class TestPlan:
    """Unit tests for Plan model"""

    def test_str(self, plan_factory):
        plan = plan_factory.build()
        assert str(plan) == plan.name

    def test_free(self, plan_factory):
        plan = plan_factory.build()
        assert plan.free

    def test_not_free(self, professional_plan_factory):
        plan = professional_plan_factory.build()
        assert not plan.free

    @pytest.mark.parametrize(
        "users,cost", [(0, 100), (1, 100), (5, 100), (7, 120), (10, 150)]
    )
    def test_cost(self, organization_plan_factory, users, cost):
        plan = organization_plan_factory.build()
        assert plan.cost(users) == cost

    def test_stripe_id(self, plan_factory):
        plan = plan_factory.build()
        assert plan.stripe_id == f"squarelet_plan_{plan.slug}"

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
    def test_accept_with_user(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        invitation.user = user_factory()
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_without_user(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        user = user_factory()
        assert invitation.user is None
        invitation.accept(user)
        assert invitation.user == user
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.django_db()
    def test_accept_missing_user(self, invitation_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory.build()
        assert invitation.user is None
        with pytest.raises(ValueError):
            invitation.accept()

    @pytest.mark.django_db()
    def test_accept_closed(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        user = user_factory.build()
        invitation = invitation_factory.build(accepted_at=timezone.now())
        with pytest.raises(ValueError):
            invitation.accept(user)

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_duplicate(
        self, invitation_factory, user_factory, membership_factory, mocker
    ):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        invitation.user = user_factory()
        membership_factory(organization=invitation.organization, user=invitation.user)
        assert invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_reject(self, invitation_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
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


class TestEntitlement:
    """Unit tests for Entitlement model"""

    @pytest.mark.django_db()
    def test_public(self):
        public_plan = PlanFactory()
        private_plan = PlanFactory(public=False)
        entitlement = EntitlementFactory()

        assert not entitlement.public

        entitlement.plans.set([private_plan])
        assert not entitlement.public

        entitlement.plans.set([public_plan])
        assert entitlement.public

        entitlement.plans.set([private_plan, public_plan])
        assert entitlement.public
