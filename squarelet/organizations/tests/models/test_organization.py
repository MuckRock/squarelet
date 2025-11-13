# Standard Library
from unittest.mock import Mock, PropertyMock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import Organization


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
