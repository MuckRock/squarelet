# Django
from django.test import override_settings
from django.utils import timezone

# Standard Library
from datetime import timedelta
from unittest.mock import MagicMock, Mock, PropertyMock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import Invoice, Organization, ReceiptEmail
from squarelet.organizations.tests.factories import EntitlementFactory, PlanFactory

# pylint: disable=too-many-public-methods,too-many-lines


def create_mock_stripe_invoice(invoice_id, amount_due, status, created, due_date=None):
    """
    Create a mock Stripe invoice object that supports dictionary-style access.

    This helper simulates how Stripe API objects work (they inherit from dict),
    allowing tests to use the same mock structure consistently.
    """
    mock_invoice = MagicMock()
    invoice_data = {
        "id": invoice_id,
        "amount_due": amount_due,
        "status": status,
        "created": created,
        "due_date": due_date,
    }
    mock_invoice.__getitem__ = MagicMock(side_effect=lambda k: invoice_data[k])
    mock_invoice.get = MagicMock(
        side_effect=lambda k, default=None: invoice_data.get(k, default)
    )
    # Also support property access (e.g., mock_invoice.id)
    mock_invoice.id = invoice_id
    return mock_invoice


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

    @pytest.mark.django_db()
    def test_save_card(self, organization_factory, mocker, user_factory):
        token = "token"
        user = user_factory()
        customer = Mock(card_display="Visa: x4242")
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=customer,
        )
        mocked_sci = mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )
        organization = organization_factory.build()
        organization.save_card(token, user)
        assert not organization.payment_failed
        customer.save_card.assert_called_with(token)
        mocked_sci.assert_called_with("organization", organization.uuid)

    @pytest.mark.django_db
    def test_set_subscription_modify_free(
        self, organization_factory, mocker, user_factory
    ):
        user = user_factory()
        organization = organization_factory()
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer", card=None
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        organization.set_subscription(None, organization.plan, max_users, user)
        organization.refresh_from_db()
        assert organization.max_users == 10

    @pytest.mark.django_db
    def test_set_subscription_create(
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
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        token = "token"
        organization.set_subscription(token, plan, max_users, user)
        mocked_save_card.assert_called_with(token, user)
        assert mocked_customer.email == organization.email
        mocked_customer.save.assert_called()
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan, payment_method="card"
        )

    @pytest.mark.django_db
    def test_set_subscription_cancel(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        plan = professional_plan_factory()
        organization = organization_factory(admins=[user], plans=[plan])
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer", card=None
        )
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
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer", card=None
        )
        mocked = mocker.patch("squarelet.organizations.models.Subscription.modify")
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        max_users = 10
        token = None
        organization.set_subscription(token, plan, max_users, user)
        mocked.assert_called_with(plan)

    @pytest.mark.django_db
    def test_set_subscription_with_invoice_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """Test that explicitly passing payment_method='invoice' uses invoice billing"""
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        # Mock that organization has a saved card
        mocked_card = mocker.MagicMock()
        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email=None,
            default_source=True,
        )
        type(mocked_customer).card = PropertyMock(return_value=mocked_card)

        mocked_subscriptions = mocker.patch(
            "squarelet.organizations.models.Organization.subscriptions"
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        max_users = 10
        token = None
        # User explicitly selects invoice payment despite having a card on file
        organization.set_subscription(
            token, plan, max_users, user, payment_method="invoice"
        )

        # Should pass "invoice" to subscriptions.start, not "card"
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan, payment_method="invoice"
        )

    @pytest.mark.django_db
    def test_set_subscription_with_existing_card_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """Test that payment_method='existing-card' maps to 'card'"""
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email=None,
        )
        mocked_subscriptions = mocker.patch(
            "squarelet.organizations.models.Organization.subscriptions"
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        max_users = 10
        token = None
        organization.set_subscription(
            token, plan, max_users, user, payment_method="existing-card"
        )

        # "existing-card" should be mapped to "card"
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan, payment_method="card"
        )

    @pytest.mark.django_db
    def test_set_subscription_with_new_card_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """Test that payment_method='new-card' maps to 'card'"""
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        mocked_save_card = mocker.patch(
            "squarelet.organizations.models.Organization.save_card"
        )
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email=None,
        )
        mocked_subscriptions = mocker.patch(
            "squarelet.organizations.models.Organization.subscriptions"
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        max_users = 10
        token = "tok_test123"
        organization.set_subscription(
            token, plan, max_users, user, payment_method="new-card"
        )

        mocked_save_card.assert_called_with(token, user)
        # "new-card" should be mapped to "card"
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan, payment_method="card"
        )

    @pytest.mark.django_db
    def test_set_subscription_backward_compatibility_no_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """
        Test backward compatibility: when payment_method not provided,
        auto-detect based on card
        """
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        # Mock that organization has a saved card
        mocked_card = mocker.MagicMock()
        mocked_customer_obj = mocker.MagicMock()
        mocked_customer_obj.email = None
        mocked_customer_obj.card = mocked_card

        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=mocked_customer_obj,
        )

        mocked_subscriptions = mocker.patch(
            "squarelet.organizations.models.Organization.subscriptions"
        )
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        max_users = 10
        token = None
        # Don't pass payment_method - should auto-detect as "card" because card exists
        organization.set_subscription(token, plan, max_users, user)

        # Should default to "card" since a card is on file
        mocked_subscriptions.start.assert_called_with(
            organization=organization, plan=plan, payment_method="card"
        )

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
        mocked_subscription.subscription_id = "sub_test123"
        # Mock the stripe_subscription property to return a mock Stripe subscription
        mock_stripe_sub = mocker.MagicMock()
        type(mocked_subscription).stripe_subscription = mocker.PropertyMock(
            return_value=mock_stripe_sub
        )

        organization.subscription_cancelled()

        mocked_change_logs.create.assert_called_with(
            reason=ChangeLogReason.failed,
            from_plan=plan,
            from_max_users=organization.max_users,
            to_max_users=organization.max_users,
        )
        # Should cancel in Stripe first by calling delete on the stripe_subscription
        mock_stripe_sub.delete.assert_called_once()
        # Then delete local subscription
        mocked_subscription.delete.assert_called()

    @pytest.mark.django_db
    def test_subscription_cancelled_without_subscription_id(
        self, organization_factory, mocker, professional_plan_factory
    ):
        """Should still delete local subscription even if no subscription_id"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory(plans=[plan])
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        mocked_subscription.subscription_id = None

        organization.subscription_cancelled()

        # Should still delete local subscription
        # (no Stripe interaction since no subscription_id)
        mocked_subscription.delete.assert_called()

    @pytest.mark.django_db
    def test_subscription_cancelled_stripe_error(
        self, organization_factory, mocker, professional_plan_factory
    ):
        """Should handle Stripe errors gracefully and still delete local subscription"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory(plans=[plan])
        mocker.patch("squarelet.organizations.models.Organization.change_logs")
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        mocked_subscription.subscription_id = "sub_test123"
        # Mock the stripe_subscription property to return a mock
        # that raises error on delete
        mock_stripe_sub = mocker.MagicMock()
        mock_stripe_sub.delete.side_effect = stripe.error.InvalidRequestError(
            "No such subscription", "subscription"
        )
        type(mocked_subscription).stripe_subscription = mocker.PropertyMock(
            return_value=mock_stripe_sub
        )

        organization.subscription_cancelled()

        # Should attempt to delete the Stripe subscription
        mock_stripe_sub.delete.assert_called_once()
        # Should still delete local subscription despite error
        mocked_subscription.delete.assert_called()

    @pytest.mark.django_db
    def test_subscription_cancelled_correct_stripe_pattern(
        self, organization_factory, mocker, professional_plan_factory
    ):
        """Test subscription_cancelled uses correct Stripe API pattern
        (retrieve then delete)"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory(plans=[plan])

        # Mock the subscription property
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        mocked_subscription.subscription_id = "sub_test123"

        # Mock the Stripe subscription instance
        mock_stripe_sub = mocker.MagicMock()
        # Mock stripe_subscription property to return the mock Stripe subscription
        type(mocked_subscription).stripe_subscription = mocker.PropertyMock(
            return_value=mock_stripe_sub
        )

        # Mock change logs
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        organization.subscription_cancelled()

        # Verify delete was called on the stripe_subscription instance
        mock_stripe_sub.delete.assert_called_once()
        # Verify local subscription was deleted
        mocked_subscription.delete.assert_called()

    @pytest.mark.django_db
    def test_subscription_cancelled_nonexistent_stripe_subscription(
        self, organization_factory, mocker, professional_plan_factory
    ):
        """Test graceful handling when Stripe subscription doesn't exist"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory(plans=[plan])

        # Mock the subscription property
        mocked_subscription = mocker.patch(
            "squarelet.organizations.models.Organization.subscription"
        )
        mocked_subscription.subscription_id = "sub_nonexistent"

        # Mock stripe_subscription property to return None (subscription doesn't exist)
        type(mocked_subscription).stripe_subscription = mocker.PropertyMock(
            return_value=None
        )

        # Mock change logs
        mocker.patch("squarelet.organizations.models.Organization.change_logs")

        # Should not raise an error
        organization.subscription_cancelled()

        # Verify local subscription was still deleted
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

    @pytest.mark.django_db()
    def test_subscribe(self, organization_factory, user_factory, mocker):
        mocked = mocker.patch("squarelet.core.utils.mailchimp_journey")
        users = user_factory.create_batch(4)
        org = organization_factory(verified_journalist=False, users=users)
        organization_factory(verified_journalist=True, users=users[2:])
        org.subscribe()
        # In test environment, MailChimp calls are skipped
        assert mocked.call_count == 0

    @pytest.mark.django_db()
    def test_merge(self, organization_factory, user_factory, plan_factory):

        users = user_factory.create_batch(4)

        # user 0 and 1 in org
        org = organization_factory(users=users[0:2])
        # user 1 and 2 in dupe org
        dupe_org = organization_factory(users=users[1:3])

        plan = plan_factory(public=False)
        plan.private_organizations.add(dupe_org)

        org.merge(dupe_org, users[0])

        # user 0, 1 and 2 in org
        for user_id in range(3):
            assert org.has_member(users[user_id])
        # user 3 not in org
        assert not org.has_member(users[3])

        # no users in dupe_org
        assert dupe_org.users.count() == 0
        assert dupe_org.private

        # private plan has moved to org
        assert plan.private_organizations.filter(pk=org.pk)
        assert not plan.private_organizations.filter(pk=dupe_org.pk)

    @pytest.mark.django_db()
    def test_merge_bad(self, organization_factory, user_factory):

        user = user_factory()
        org = organization_factory()
        dupe_org = organization_factory(merged=org)

        error_msg = f"{dupe_org} has already been merged, and may not be merged again"
        with pytest.raises(ValueError, match=error_msg):
            org.merge(dupe_org, user)

    @pytest.mark.django_db()
    def test_merge_fks(self):
        # Relations pointing to the Organization model
        assert (
            len(
                [
                    f
                    for f in Organization._meta.get_fields()
                    if f.is_relation and f.auto_created
                ]
            )
            == 14
        )
        # Many to many relations defined on the Organization model
        assert (
            len(
                [
                    f
                    for f in Organization._meta.get_fields()
                    if f.many_to_many and not f.auto_created
                ]
            )
            == 4
        )


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
        assert customer.card_display == f"{brand}: x{last4}"

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

    @pytest.mark.django_db()
    def test_customer_invalid_clears_and_creates_new(self, customer_factory, mocker):
        """Test that an invalid customer_id is cleared and a new customer is created"""
        old_customer_id = "cus_invalid_id"
        new_customer_id = "cus_new_id"

        # Mock stripe.Customer.retrieve to raise InvalidRequestError for old ID only
        def mock_retrieve(customer_id):
            if customer_id == old_customer_id:
                error = stripe.error.InvalidRequestError(
                    "No such customer: 'cus_invalid_id'; a similar object "
                    "exists in live mode, but a test mode key was used "
                    "to make this request.",
                    "id",
                )
                error.code = "resource_missing"
                raise error
            # If called with a different ID (e.g., new customer created by
            # another thread), return a mock customer
            return Mock(id=customer_id, name="Test Customer")

        mocked_retrieve = mocker.patch(
            "stripe.Customer.retrieve",
            side_effect=mock_retrieve,
        )

        # Mock stripe.Customer.create to return a new customer
        mock_new_customer = Mock(id=new_customer_id)
        mocked_create = mocker.patch(
            "stripe.Customer.create", return_value=mock_new_customer
        )

        # Create a customer with an invalid customer_id
        email = "email@example.com"
        mocker.patch("squarelet.organizations.models.Organization.email", email)
        customer = customer_factory(customer_id=old_customer_id)

        # Access stripe_customer property - should clear invalid ID and create new one
        result = customer.stripe_customer

        # Verify the retrieve was called with the old ID
        mocked_retrieve.assert_called_with(old_customer_id)

        # Verify a new customer was created
        mocked_create.assert_called_with(
            description=customer.organization.name,
            email=email,
            name=customer.organization.user_full_name,
        )

        # Verify the result is the new customer
        assert result == mock_new_customer

        # Verify the customer_id was updated in the database
        customer.refresh_from_db()
        assert customer.customer_id == new_customer_id


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

    @pytest.mark.django_db()
    def test_start(self, subscription_factory, professional_plan_factory, mocker):
        plan = professional_plan_factory()
        subscription = subscription_factory(plan=plan)

        # Mock stripe subscription creation
        stripe_subscription_id = "sub_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id,
            latest_invoice=None,  # No invoice to avoid invoice creation path
        )
        mocked_customer = Mock()
        mocked_customer.stripe_customer.subscriptions.create.return_value = (
            mock_stripe_subscription
        )
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )

        subscription.start()

        mocked_customer.stripe_customer.subscriptions.create.assert_called_with(
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
        assert subscription.subscription_id == stripe_subscription_id

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

    @pytest.mark.django_db()
    def test_start_creates_invoice_with_card(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        """Test that subscription.start() creates an Invoice record for card payment"""
        plan = professional_plan_factory()
        subscription = subscription_factory(plan=plan)

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_test123"
        stripe_invoice_id = "in_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, latest_invoice=stripe_invoice_id
        )
        # Mock stripe invoice using helper function
        mock_stripe_invoice = create_mock_stripe_invoice(
            invoice_id=stripe_invoice_id,
            amount_due=2000,  # $20.00
            status="open",
            created=1234567890,
            due_date=None,
        )

        mocked_customer = Mock()
        mocked_customer.stripe_customer.subscriptions.create.return_value = (
            mock_stripe_subscription
        )
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mocker.patch("stripe.Invoice.retrieve", return_value=mock_stripe_invoice)
        # Start the subscription
        subscription.start(payment_method="card")

        # Verify Stripe subscription was created
        assert subscription.subscription_id == stripe_subscription_id

        # Verify Invoice record was created
        invoice = Invoice.objects.filter(invoice_id=stripe_invoice_id).first()
        assert invoice is not None, "Invoice should be created synchronously"
        assert invoice.organization == subscription.organization
        assert invoice.subscription == subscription
        assert invoice.amount == 2000
        assert invoice.status == "open"

    @pytest.mark.django_db()
    def test_start_creates_invoice_with_invoice_payment(
        self, subscription_factory, plan_factory, mocker
    ):
        """Test that subscription.start() creates Invoice for invoice payment method"""
        # Mock Stripe Plan creation
        mocker.patch("stripe.Plan.create")

        # Create annual plan
        plan = plan_factory(
            name="Annual Professional",
            annual=True,
            base_price=240,
            minimum_users=1,
        )
        subscription = subscription_factory(plan=plan)

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_annual123"
        stripe_invoice_id = "in_annual123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, latest_invoice=stripe_invoice_id
        )
        # Mock stripe invoice using helper function
        mock_stripe_invoice = create_mock_stripe_invoice(
            invoice_id=stripe_invoice_id,
            amount_due=24000,  # $240.00 annual
            status="open",
            created=1234567890,
            due_date=1234657890,  # 30 days later
        )

        mocked_customer = Mock()
        mocked_customer.stripe_customer.subscriptions.create.return_value = (
            mock_stripe_subscription
        )
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mocker.patch("stripe.Invoice.retrieve", return_value=mock_stripe_invoice)

        # Start the subscription with invoice payment
        subscription.start(payment_method="invoice")

        # Verify subscription was created with send_invoice billing
        mocked_customer.stripe_customer.subscriptions.create.assert_called_with(
            items=[
                {
                    "plan": subscription.plan.stripe_id,
                    "quantity": subscription.organization.max_users,
                }
            ],
            billing="send_invoice",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=30,
        )

        # Verify Invoice record was created
        invoice = Invoice.objects.filter(invoice_id=stripe_invoice_id).first()
        assert invoice is not None
        assert invoice.organization == subscription.organization
        assert invoice.subscription == subscription
        assert invoice.due_date is not None

    @pytest.mark.django_db()
    def test_start_free_plan_no_invoice(
        self, subscription_factory, plan_factory, mocker
    ):
        """Test that free plans don't create invoices"""
        mocker.patch("stripe.Plan.create")
        plan = plan_factory()  # Free plan (no base_price = free)
        subscription = subscription_factory(plan=plan)

        mocked_customer = mocker.patch(
            "squarelet.organizations.models.Organization.customer"
        )

        # Start the subscription
        subscription.start(payment_method="card")

        # Verify no Stripe subscription was created
        assert mocked_customer.call_count == 0

        # Verify no Invoice was created
        assert Invoice.objects.count() == 0

    @pytest.mark.django_db()
    def test_start_handles_stripe_invoice_retrieval_error(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        """Test that subscription still succeeds if invoice retrieval fails"""
        plan = professional_plan_factory()
        subscription = subscription_factory(plan=plan)

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, latest_invoice="in_test123"
        )

        mocked_customer = Mock()
        mocked_customer.stripe_customer.subscriptions.create.return_value = (
            mock_stripe_subscription
        )
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )

        # Mock Invoice.retrieve to raise an error
        mocker.patch(
            "stripe.Invoice.retrieve",
            side_effect=stripe.error.InvalidRequestError("No such invoice", "invoice"),
        )

        # Start should still succeed
        subscription.start(payment_method="card")

        # Verify subscription was still created
        assert subscription.subscription_id == stripe_subscription_id

        # Invoice won't be created due to error (webhook will handle it)
        assert Invoice.objects.count() == 0


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

    @pytest.mark.django_db
    def test_has_available_slots_non_sunlight_plan(self, plan_factory):
        """Non-Sunlight plans always have available slots"""
        plan = plan_factory(slug="professional", wix=False)
        assert plan.has_available_slots() is True

    @pytest.mark.django_db
    def test_has_available_slots_sunlight_no_wix(self, plan_factory):
        """Sunlight plans with wix=False have no limit"""
        plan = plan_factory(slug="sunlight-essential", wix=False)
        assert plan.has_available_slots() is True

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_under_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan under limit has available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 10 active subscriptions (under limit of 15)
        subscription_factory.create_batch(10, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is True

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_at_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan at limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 15 active subscriptions (at limit)
        subscription_factory.create_batch(15, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_over_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan over limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 20 active subscriptions (over limit)
        subscription_factory.create_batch(20, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_counts_all_sunlight_variants(
        self, plan_factory, subscription_factory
    ):
        """Limit is shared across all Sunlight plan variants"""
        sunlight_basic = plan_factory(slug="sunlight-essential-monthly", wix=True)
        sunlight_premium = plan_factory(slug="sunlight-enhanced-annual", wix=True)

        # Create 10 subscriptions for basic, 5 for premium (total 15)
        for _ in range(10):
            subscription_factory(plan=sunlight_basic, cancelled=False)
        for _ in range(5):
            subscription_factory(plan=sunlight_premium, cancelled=False)

        # Both plans should show no slots available
        assert sunlight_basic.has_available_slots() is False
        assert sunlight_premium.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_excludes_cancelled(
        self, plan_factory, subscription_factory
    ):
        """Cancelled subscriptions don't count toward limit"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 14 active and 10 cancelled subscriptions
        for _ in range(14):
            subscription_factory(plan=sunlight_plan, cancelled=False)
        for _ in range(10):
            subscription_factory(plan=sunlight_plan, cancelled=True)

        # Should still have slots available (14 < 15)
        assert sunlight_plan.has_available_slots() is True

    def test_is_sunlight_plan_for_regular_sunlight(self, plan_factory):
        """Regular Sunlight plans should be identified as Sunlight plans"""
        plan = plan_factory.build(slug="sunlight-essential")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-enhanced-annual")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-enterprise")
        assert plan.is_sunlight_plan is True

    def test_is_sunlight_plan_for_nonprofit_sunlight(self, plan_factory):
        """Nonprofit Sunlight plans should be identified as Sunlight plans"""
        plan = plan_factory.build(slug="sunlight-nonprofit-essential")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-nonprofit-enhanced-annual")
        assert plan.is_sunlight_plan is True

    def test_is_sunlight_plan_for_non_sunlight(self, plan_factory):
        """Non-Sunlight plans should not be identified as Sunlight plans"""
        plan = plan_factory.build(slug="professional")
        assert plan.is_sunlight_plan is False

        plan = plan_factory.build(slug="organization")
        assert plan.is_sunlight_plan is False

        plan = plan_factory.build(slug="free")
        assert plan.is_sunlight_plan is False

    def test_nonprofit_variant_slug_for_regular_sunlight(self, plan_factory):
        """Regular Sunlight plans should return nonprofit variant slug"""
        plan = plan_factory.build(slug="sunlight-essential")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-essential"

        plan = plan_factory.build(slug="sunlight-enhanced-annual")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enhanced-annual"

        plan = plan_factory.build(slug="sunlight-enterprise")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enterprise"

    def test_nonprofit_variant_slug_for_nonprofit_sunlight(self, plan_factory):
        """Nonprofit Sunlight plans should return their own slug"""
        plan = plan_factory.build(slug="sunlight-nonprofit-essential")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-essential"

        plan = plan_factory.build(slug="sunlight-nonprofit-enhanced-annual")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enhanced-annual"

    def test_nonprofit_variant_slug_for_non_sunlight(self, plan_factory):
        """Non-Sunlight plans should return None"""
        plan = plan_factory.build(slug="professional")
        assert plan.nonprofit_variant_slug is None

        plan = plan_factory.build(slug="organization")
        assert plan.nonprofit_variant_slug is None

        plan = plan_factory.build(slug="free")
        assert plan.nonprofit_variant_slug is None


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
    def test_accept_verified(self, invitation_factory, user_factory, mocker):
        mocked = mocker.patch("squarelet.core.utils.mailchimp_journey")
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory(organization__verified_journalist=True)
        invitation.user = user_factory()
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()
        # In test environments, MailChimp calls are skipped
        assert mocked.call_count == 0

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_verified_verified(self, invitation_factory, user_factory, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.organization.mailchimp_journey"
        )
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory(organization__verified_journalist=True)
        invitation.user = user_factory(
            individual_organization__verified_journalist=True
        )
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()
        mocked.assert_not_called()

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
        assert invitation.get_name() == f"{invitation.user.name} ({invitation.email})"


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


class TestInvoice:
    """Unit tests for Invoice model"""

    def test_str(self, invoice_factory):
        invoice = invoice_factory.build(
            invoice_id="in_12345", amount=10000, status="open"
        )
        assert str(invoice) == "Invoice in_12345 - $100.00 (open)"

    def test_amount_dollars(self, invoice_factory):
        invoice = invoice_factory.build(amount=12345)
        assert invoice.amount_dollars == 123.45

    @pytest.mark.django_db
    def test_is_overdue_true_for_past_due(self, invoice_factory):
        """Test is_overdue returns True for open invoice past due date"""
        past_due_date = timezone.now().date() - timedelta(days=1)
        invoice = invoice_factory(status="open", due_date=past_due_date)
        assert invoice.is_overdue is True

    @pytest.mark.django_db
    def test_is_overdue_false_for_future_due(self, invoice_factory):
        """Test is_overdue returns False for open invoice with future due date"""
        future_due_date = timezone.now().date() + timedelta(days=30)
        invoice = invoice_factory(status="open", due_date=future_due_date)
        assert invoice.is_overdue is False

    @pytest.mark.django_db
    def test_is_overdue_false_for_paid_invoice(self, invoice_factory):
        """Test is_overdue returns False for paid invoice even if past due"""
        past_due_date = timezone.now().date() - timedelta(days=30)
        invoice = invoice_factory(status="paid", due_date=past_due_date)
        assert invoice.is_overdue is False

    @pytest.mark.django_db
    def test_is_overdue_false_for_no_due_date(self, invoice_factory):
        """Test is_overdue returns False when invoice has no due date"""
        invoice = invoice_factory(status="open", due_date=None)
        assert invoice.is_overdue is False

    def test_amount_none(self, invoice_factory):
        """Test formatting logic when amount is None"""
        invoice = invoice_factory.build(
            invoice_id="in_12345", amount=None, status="open"
        )
        assert invoice.amount_dollars == 0.0
        assert str(invoice) == "Invoice in_12345 - $0.00 (open)"

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_dict_access(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe with dictionary (webhook scenario)"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        # Simulate webhook data - plain dictionary
        stripe_invoice_dict = {
            "id": "in_webhook123",
            "amount_due": 5000,  # $50.00
            "status": "open",
            "created": 1234567890,
            "due_date": 1234657890,  # 30 days later
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, subscription
        )

        assert created is True
        assert invoice.invoice_id == "in_webhook123"
        assert invoice.organization == organization
        assert invoice.subscription == subscription
        assert invoice.amount == 5000
        assert invoice.status == "open"
        assert invoice.due_date is not None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_object_access(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe with Stripe object (API scenario)"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        # Simulate Stripe API object using helper function
        mock_stripe_invoice = create_mock_stripe_invoice(
            invoice_id="in_api456",
            amount_due=10000,  # $100.00
            status="paid",
            created=1234567890,
            due_date=None,
        )

        invoice, created = Invoice.create_or_update_from_stripe(
            mock_stripe_invoice, organization, subscription
        )

        assert created is True
        assert invoice.invoice_id == "in_api456"
        assert invoice.organization == organization
        assert invoice.subscription == subscription
        assert invoice.amount == 10000
        assert invoice.status == "paid"
        assert invoice.due_date is None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_updates_existing(
        self, organization_factory, invoice_factory
    ):
        """Test that create_or_update_from_stripe updates existing invoices"""
        organization = organization_factory()
        existing_invoice = invoice_factory(
            invoice_id="in_existing789",
            organization=organization,
            amount=5000,
            status="open",
        )

        # Update with new data
        stripe_invoice_dict = {
            "id": "in_existing789",
            "amount_due": 7500,  # Changed amount
            "status": "paid",  # Changed status
            "created": 1234567890,
            "due_date": None,
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, None
        )

        assert created is False
        assert invoice.id == existing_invoice.id
        assert invoice.amount == 7500
        assert invoice.status == "paid"

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_no_due_date(
        self, organization_factory, subscription_factory
    ):
        """Test create_or_update_from_stripe handles None due_date correctly"""
        organization = organization_factory()
        subscription = subscription_factory(organization=organization)

        stripe_invoice_dict = {
            "id": "in_no_due_date",
            "amount_due": 2000,
            "status": "draft",
            "created": 1234567890,
            "due_date": None,  # No due date
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, subscription
        )

        assert created is True
        assert invoice.due_date is None

    @pytest.mark.django_db
    def test_create_or_update_from_stripe_no_subscription(self, organization_factory):
        """Test create_or_update_from_stripe works without subscription"""
        organization = organization_factory()

        stripe_invoice_dict = {
            "id": "in_no_sub",
            "amount_due": 3000,
            "status": "open",
            "created": 1234567890,
            "due_date": 1234657890,
        }

        invoice, created = Invoice.create_or_update_from_stripe(
            stripe_invoice_dict, organization, None
        )

        assert created is True
        assert invoice.subscription is None
        assert invoice.organization == organization

    @pytest.mark.django_db
    def test_mark_uncollectible_in_stripe_success(self, invoice_factory, mocker):
        """Test mark_uncollectible_in_stripe successfully marks invoice"""
        invoice = invoice_factory(invoice_id="in_test123", status="open")

        # Mock the Stripe API request
        mock_requestor = mocker.MagicMock()
        mock_requestor.request.return_value = (mocker.MagicMock(), "api_key")
        mocker.patch("stripe.api_requestor.APIRequestor", return_value=mock_requestor)

        # Call the method
        invoice.mark_uncollectible_in_stripe()

        # Verify Stripe API was called correctly
        mock_requestor.request.assert_called_once_with(
            "post",
            "/v1/invoices/in_test123/mark_uncollectible",
            {},
        )

    @pytest.mark.django_db
    def test_mark_uncollectible_in_stripe_stripe_error(self, invoice_factory, mocker):
        """Test mark_uncollectible_in_stripe handles Stripe errors"""
        invoice = invoice_factory(invoice_id="in_error123", status="open")

        # Mock the Stripe API request to raise an error
        mock_requestor = mocker.MagicMock()
        mock_requestor.request.side_effect = stripe.error.InvalidRequestError(
            "This invoice has already been marked uncollectible", "invoice"
        )
        mocker.patch("stripe.api_requestor.APIRequestor", return_value=mock_requestor)

        # Should raise the Stripe error
        with pytest.raises(stripe.error.InvalidRequestError):
            invoice.mark_uncollectible_in_stripe()
