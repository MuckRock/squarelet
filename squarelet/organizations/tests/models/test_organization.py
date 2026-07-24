# Standard Library
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import Mock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import Organization, Subscription
from squarelet.organizations.payments.exceptions import SubscriptionError

# pylint: disable=too-many-public-methods,too-many-lines,too-many-positional-arguments


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
    def test_has_sole_admin(self, organization_factory, user_factory):
        """A user who is the only admin is the sole admin"""
        admin, member = user_factory.create_batch(2)
        org = organization_factory(users=[member], admins=[admin])

        assert org.has_sole_admin(admin)
        # A regular member is never a sole admin
        assert not org.has_sole_admin(member)

    @pytest.mark.django_db()
    def test_has_sole_admin_multiple_admins(self, organization_factory, user_factory):
        """When there are multiple admins, none of them is the sole admin"""
        admin1, admin2 = user_factory.create_batch(2)
        org = organization_factory(admins=[admin1, admin2])

        assert not org.has_sole_admin(admin1)
        assert not org.has_sole_admin(admin2)

    @pytest.mark.django_db()
    def test_has_sole_admin_non_member(self, organization_factory, user_factory):
        """A user who is not an admin at all is not the sole admin, even
        when the org has exactly one admin"""
        admin, outsider = user_factory.create_batch(2)
        org = organization_factory(admins=[admin])

        assert not org.has_sole_admin(outsider)

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
        assert organization.subscriptions.first() is None

    @pytest.mark.django_db()
    def test_save_card(self, organization_factory, mocker, user_factory):
        token = "token"
        user = user_factory()
        customer = Mock(payment_method_display="Visa: x4242")
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

    def _setup_stripe_mock(self, mocker, period_end=1_800_000_000, status="active"):
        """Mock the Stripe customer and subscription service. Returns
        (mock_customer, mock_sub_service, mock_stripe_sub)."""
        mock_customer = mocker.MagicMock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mock_customer,
        )
        mock_stripe_sub = Mock(
            id="sub_test123",
            status=status,
            latest_invoice=None,
        )
        # Patch the subscription service used by Subscription.start() in payment.py
        mock_sub_service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_service.create.return_value = mock_stripe_sub
        # Patch the provider reference used by add_subscription() in organization.py
        # for get_current_period_end (field moved to subscription items in basil API)
        mock_org_sub_service = mocker.patch(
            "squarelet.organizations.models.organization.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_org_sub_service.get_current_period_end.return_value = period_end
        return mock_customer, mock_sub_service, mock_stripe_sub

    @pytest.mark.django_db
    def test_add_subscription(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """Adding a subscription creates a Subscription record, passes quantity to
        Stripe, and sets org.update_on from Stripe's current_period_end."""

        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()
        max_users = 5
        period_end = 1_800_000_000

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(
            mocker, period_end=period_end
        )
        mocker.patch("squarelet.organizations.models.Organization.save_card")

        organization.add_subscription(plan, max_users, user, token="tok_visa")

        sub = organization.subscriptions.get(plan=plan)
        assert sub.quantity == max_users

        organization.refresh_from_db()
        expected_date = datetime.fromtimestamp(period_end, tz=dt_timezone.utc).date()
        assert organization.update_on == expected_date
        assert organization.billing_anchor == expected_date

        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan.stripe_id,
            quantity=max_users,
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_add_second_subscription_uses_billing_anchor(
        self,
        organization_factory,
        mocker,
        user_factory,
        plan_factory,
    ):
        """A second subscription passes billing_anchor day to Stripe as
        billing_cycle_anchor_config."""

        user = user_factory()
        plan_b = plan_factory(annual=False, base_price=10, minimum_users=1)
        mocker.patch("stripe.Plan.create")

        # Set org with a billing_anchor that differs from update_on.
        anchor = date(2027, 1, 15)
        update = date(2026, 8, 15)
        organization = organization_factory(
            admins=[user], billing_anchor=anchor, update_on=update
        )

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(mocker)

        organization.add_subscription(plan_b, 1, user, payment_method="card")

        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan_b.stripe_id,
            quantity=1,
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan_b.name})"},
            days_until_due=None,
            anchor_day=15,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_add_subscription_with_invoice_payment_method(
        self, organization_factory, mocker, user_factory, plan_factory
    ):
        """Annual plan with payment_method='invoice' uses send_invoice billing."""
        mocker.patch("stripe.Plan.create")
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = plan_factory(annual=True, base_price=240, minimum_users=1)

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(mocker)

        organization.add_subscription(plan, 1, user, payment_method="invoice")

        assert organization.subscriptions.filter(plan=plan).exists()
        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan.stripe_id,
            quantity=1,
            billing="send_invoice",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=30,
            anchor_day=None,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_add_subscription_with_existing_card_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """payment_method='existing-card' is normalised to card billing."""
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(mocker)

        organization.add_subscription(plan, 3, user, payment_method="existing-card")

        assert organization.subscriptions.filter(plan=plan).exists()
        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan.stripe_id,
            quantity=3,
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_add_subscription_with_new_card_payment_method(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """payment_method='new-card' saves the card and uses card billing."""
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(mocker)
        mocked_save_card = mocker.patch(
            "squarelet.organizations.models.Organization.save_card"
        )

        token = "tok_test123"
        organization.add_subscription(
            plan, 2, user, token=token, payment_method="new-card"
        )

        mocked_save_card.assert_called_with(token, user)
        assert organization.subscriptions.filter(plan=plan).exists()
        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan.stripe_id,
            quantity=2,
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_add_subscription_auto_detects_card(
        self, organization_factory, mocker, user_factory, professional_plan_factory
    ):
        """When no payment_method is provided and a card is on file, card billing
        is auto-detected and used."""
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = professional_plan_factory()

        mock_customer, mock_sub_service, _ = self._setup_stripe_mock(mocker)
        mock_customer.payment_details = mocker.MagicMock()  # payment method on file

        organization.add_subscription(plan, 4, user)

        assert organization.subscriptions.filter(plan=plan).exists()
        mock_sub_service.create.assert_called_with(
            stripe_customer=mock_customer.stripe_customer,
            plan_id=plan.stripe_id,
            quantity=4,
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=False,
        )

    @pytest.mark.django_db
    def test_subscription_cancelled(
        self,
        organization_factory,
        mocker,
        professional_plan_factory,
        subscription_factory,
    ):
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory()
        sub = subscription_factory(
            organization=organization, plan=plan, subscription_id="sub_test123"
        )
        # Inject mock Stripe subscription via cached_property's __dict__ slot
        mock_stripe_sub = mocker.MagicMock()
        sub.__dict__["stripe_subscription"] = mock_stripe_sub

        organization.subscription_cancelled(subscription=sub)

        # Should cancel in Stripe first by calling delete on the stripe_subscription
        mock_stripe_sub.delete.assert_called_once()
        # Local subscription should be deleted
        assert not Subscription.objects.filter(pk=sub.pk).exists()

    @pytest.mark.django_db
    def test_subscription_cancelled_without_subscription_id(
        self,
        organization_factory,
        mocker,
        professional_plan_factory,
        subscription_factory,
    ):
        """Should still delete local subscription even if no subscription_id"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory()
        sub = subscription_factory(
            organization=organization, plan=plan, subscription_id=None
        )

        organization.subscription_cancelled(subscription=sub)

        # Should still delete local subscription
        assert not Subscription.objects.filter(pk=sub.pk).exists()

    @pytest.mark.django_db
    def test_subscription_cancelled_stripe_error(
        self,
        organization_factory,
        mocker,
        professional_plan_factory,
        subscription_factory,
    ):
        """Should handle Stripe errors gracefully and still delete local subscription"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory()
        sub = subscription_factory(
            organization=organization, plan=plan, subscription_id="sub_test123"
        )

        mock_stripe_sub = mocker.MagicMock()
        mock_stripe_sub.delete.side_effect = stripe.InvalidRequestError(
            "No such subscription", "subscription"
        )
        mock_provider = mocker.MagicMock()
        mock_provider.get_subscription_service.return_value.retrieve.return_value = (
            mock_stripe_sub
        )
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider",
            return_value=mock_provider,
        )

        organization.subscription_cancelled(subscription=sub)

        # Should attempt to delete the Stripe subscription
        mock_stripe_sub.delete.assert_called_once()
        # Should still delete local subscription despite error
        assert not Subscription.objects.filter(pk=sub.pk).exists()

    @pytest.mark.django_db
    def test_subscription_cancelled_correct_stripe_pattern(
        self,
        organization_factory,
        mocker,
        professional_plan_factory,
        subscription_factory,
    ):
        """Test subscription_cancelled uses correct Stripe API pattern
        (retrieve then delete)"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory()
        sub = subscription_factory(
            organization=organization, plan=plan, subscription_id="sub_test123"
        )
        mock_stripe_sub = mocker.MagicMock()
        mock_provider = mocker.MagicMock()
        mock_provider.get_subscription_service.return_value.retrieve.return_value = (
            mock_stripe_sub
        )
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider",
            return_value=mock_provider,
        )

        organization.subscription_cancelled(subscription=sub)

        # Verify delete was called on the stripe_subscription instance
        mock_stripe_sub.delete.assert_called_once()
        # Verify local subscription was deleted
        assert not Subscription.objects.filter(pk=sub.pk).exists()

    @pytest.mark.django_db
    def test_subscription_cancelled_nonexistent_stripe_subscription(
        self,
        organization_factory,
        mocker,
        professional_plan_factory,
        subscription_factory,
    ):
        """Test graceful handling when Stripe subscription doesn't exist"""
        mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory()
        organization = organization_factory()
        sub = subscription_factory(
            organization=organization, plan=plan, subscription_id="sub_nonexistent"
        )
        mock_provider = mocker.MagicMock()
        # stripe_subscription returns None (subscription doesn't exist on Stripe)
        mock_provider.get_subscription_service.return_value.retrieve.return_value = None
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider",
            return_value=mock_provider,
        )

        # Should not raise an error
        organization.subscription_cancelled(subscription=sub)

        # Verify local subscription was still deleted
        assert not Subscription.objects.filter(pk=sub.pk).exists()

    @pytest.mark.django_db(transaction=True)
    def test_subscription_cancelled_removes_wix_labels(
        self, organization_factory, mocker, plan_factory, user_factory
    ):
        """Should trigger Wix unsync for all users when subscription is cancelled"""
        wix_plan = plan_factory(wix=True)
        user1 = user_factory()
        user2 = user_factory()
        organization = organization_factory(plans=[wix_plan], users=[user1, user2])

        sub = organization.subscriptions.first()
        sub.__dict__["stripe_subscription"] = None  # no Stripe sub to cancel

        mock_unsync = mocker.patch("squarelet.organizations.tasks.unsync_wix.delay")

        organization.subscription_cancelled(subscription=sub)

        # Should call unsync for each user
        assert mock_unsync.call_count == 2
        called_user_ids = {call.args[2] for call in mock_unsync.call_args_list}
        assert called_user_ids == {user1.pk, user2.pk}

    @pytest.mark.django_db(transaction=True)
    def test_subscription_cancelled_no_wix_no_unsync(
        self, organization_factory, mocker, plan_factory, user_factory
    ):
        """Should not trigger Wix unsync when plan is not Wix"""
        non_wix_plan = plan_factory(wix=False)
        user = user_factory()
        organization = organization_factory(plans=[non_wix_plan], users=[user])

        sub = organization.subscriptions.first()
        sub.__dict__["stripe_subscription"] = None

        mock_unsync = mocker.patch("squarelet.organizations.tasks.unsync_wix.delay")

        organization.subscription_cancelled(subscription=sub)

        mock_unsync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_modify_subscription_changes_plan(
        self, organization_factory, user_factory, plan_factory
    ):
        """modify_subscription updates the subscription to the new plan"""
        old_plan = plan_factory(slug="sunlight-enterprise", wix=True)
        new_plan = plan_factory(slug="sunlight-essential", wix=True)
        user = user_factory()
        organization = organization_factory(admins=[user], plans=[old_plan])

        organization.modify_subscription(old_plan, new_plan, 5, user)

        assert organization.subscriptions.filter(plan=new_plan).exists()

    @pytest.mark.django_db(transaction=True)
    def test_remove_subscription_wix_removes_labels(
        self, organization_factory, mocker, user_factory, plan_factory
    ):
        """Cancelling a Wix plan subscription should unsync labels"""
        wix_plan = plan_factory(wix=True)
        user = user_factory()
        organization = organization_factory(admins=[user], plans=[wix_plan])

        mock_unsync = mocker.patch("squarelet.organizations.tasks.unsync_wix.delay")

        organization.remove_subscription(wix_plan)

        assert mock_unsync.call_count >= 1

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
            == 18
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

    @pytest.mark.django_db()
    def test_get_effective_verification_own(self, organization_factory):
        """Test verification when org is directly verified"""
        org = organization_factory(verified_journalist=True)
        assert org.get_effective_verification()

    @pytest.mark.django_db()
    def test_get_effective_verification_not_verified(self, organization_factory):
        """Test verification when org is not verified"""
        org = organization_factory(verified_journalist=False)
        assert not org.get_effective_verification()

    @pytest.mark.django_db()
    def test_get_effective_verification_from_group(self, organization_factory):
        """Test verification inherited from membership group"""
        org = organization_factory(verified_journalist=False)
        group = organization_factory(verified_journalist=True, collective_enabled=True)
        group.members.add(org)
        assert org.get_effective_verification()

    @pytest.mark.django_db()
    def test_get_effective_verification_from_parent(self, organization_factory):
        """Test verification inherited from parent"""
        parent = organization_factory(verified_journalist=True, collective_enabled=True)
        child = organization_factory(verified_journalist=False, parent=parent)
        assert child.get_effective_verification()

    @pytest.mark.django_db()
    def test_get_effective_verification_recursive(self, organization_factory):
        """Test verification inherited recursively through parent chain"""
        grandparent = organization_factory(
            verified_journalist=True, collective_enabled=True
        )
        parent = organization_factory(
            verified_journalist=False, parent=grandparent, collective_enabled=True
        )
        child = organization_factory(verified_journalist=False, parent=parent)
        assert child.get_effective_verification()

    @pytest.mark.django_db()
    def test_can_invite_org_members_admin(self, organization_factory, user_factory):
        """Test that admin of collective-enabled org can invite members"""
        user = user_factory()
        org = organization_factory(
            individual=False, collective_enabled=True, admins=[user]
        )
        assert org.can_invite_org_members(user)

    @pytest.mark.django_db()
    def test_can_invite_org_members_not_admin(self, organization_factory, user_factory):
        """Test that non-admin cannot invite members"""
        user = user_factory()
        org = organization_factory(
            individual=False, collective_enabled=True, users=[user]
        )
        assert not org.can_invite_org_members(user)

    @pytest.mark.django_db()
    def test_can_invite_org_members_not_collective(
        self, organization_factory, user_factory
    ):
        """Test that admin of non-collective org cannot invite members"""
        user = user_factory()
        org = organization_factory(
            individual=False, collective_enabled=False, admins=[user]
        )
        assert not org.can_invite_org_members(user)

    @pytest.mark.django_db()
    def test_can_invite_org_members_individual(
        self, organization_factory, user_factory
    ):
        """Test that individual orgs cannot invite members"""
        user = user_factory()
        org = organization_factory(
            individual=True, collective_enabled=True, admins=[user]
        )
        assert not org.can_invite_org_members(user)

    # Tests for get_wix_plans_from_groups()

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_no_groups(self, organization_factory):
        """Test returns empty list when org has no groups"""
        org = organization_factory()
        assert org.get_wix_plans_from_groups() == []

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_with_wix_plan(
        self, organization_factory, plan_factory
    ):
        """Test returns plan when group has Wix plan and share_resources=True"""
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        result = member_org.get_wix_plans_from_groups()
        assert len(result) == 1
        assert result[0] == (group, wix_plan)

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_share_resources_false(
        self, organization_factory, plan_factory
    ):
        """Test returns empty when share_resources=False"""
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=False, plans=[wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        assert member_org.get_wix_plans_from_groups() == []

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_non_wix_plan(
        self, organization_factory, plan_factory
    ):
        """Test returns empty when group has non-Wix plan"""
        non_wix_plan = plan_factory(wix=False)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[non_wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        assert member_org.get_wix_plans_from_groups() == []

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_parent_with_wix_plan(
        self, organization_factory, plan_factory
    ):
        """Test returns plan from parent with Wix plan and share_resources=True"""
        wix_plan = plan_factory(wix=True)
        parent = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        child = organization_factory(parent=parent)

        result = child.get_wix_plans_from_groups()
        assert len(result) == 1
        assert result[0] == (parent, wix_plan)

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_recursive_parent(
        self, organization_factory, plan_factory
    ):
        """Test returns plan from grandparent through recursive lookup"""
        wix_plan = plan_factory(wix=True)
        grandparent = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        parent = organization_factory(
            parent=grandparent, collective_enabled=True, share_resources=True
        )
        child = organization_factory(parent=parent)

        result = child.get_wix_plans_from_groups()
        # Should find grandparent's plan through parent
        assert len(result) == 1
        assert result[0] == (grandparent, wix_plan)

    @pytest.mark.django_db()
    def test_get_wix_plans_from_groups_multiple_groups(
        self, organization_factory, plan_factory
    ):
        """Test returns plans from multiple groups"""
        wix_plan1 = plan_factory(wix=True)
        wix_plan2 = plan_factory(wix=True)
        group1 = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan1]
        )
        group2 = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan2]
        )
        member_org = organization_factory()
        group1.members.add(member_org)
        group2.members.add(member_org)

        result = member_org.get_wix_plans_from_groups()
        assert len(result) == 2
        # Check both plans are in result (order may vary)
        plans_in_result = [plan for _, plan in result]
        assert wix_plan1 in plans_in_result
        assert wix_plan2 in plans_in_result

    # Tests for get_inherited_plans()

    @pytest.mark.django_db()
    def test_get_inherited_plans_no_parent_or_groups(self, organization_factory):
        """Returns empty when org has no parent and no groups"""
        org = organization_factory()
        assert org.get_inherited_plans() == []

    @pytest.mark.django_db()
    def test_get_inherited_plans_parent_without_share_resources(
        self, organization_factory, plan_factory
    ):
        """Parent must have share_resources=True to inherit"""
        paid_plan = plan_factory(base_price=100)
        parent = organization_factory(share_resources=False, plans=[paid_plan])
        child = organization_factory(parent=parent)

        assert child.get_inherited_plans() == []

    @pytest.mark.django_db()
    def test_get_inherited_plans_parent_with_no_plan(self, organization_factory):
        """Returns empty when sharing parent has no plan"""
        parent = organization_factory(share_resources=True)
        child = organization_factory(parent=parent)

        assert child.get_inherited_plans() == []

    @pytest.mark.django_db()
    def test_get_inherited_plans_parent_with_paid_plan(
        self, organization_factory, plan_factory
    ):
        """Returns (parent, plan) when parent shares a paid plan"""
        paid_plan = plan_factory(base_price=100)
        parent = organization_factory(share_resources=True, plans=[paid_plan])
        child = organization_factory(parent=parent)

        result = child.get_inherited_plans()
        assert result == [(parent, paid_plan)]

    @pytest.mark.django_db()
    def test_get_inherited_plans_excludes_free_plan(
        self, organization_factory, plan_factory
    ):
        """Free plans are not considered inherited benefits"""
        free_plan = plan_factory(base_price=0, price_per_user=0)
        parent = organization_factory(share_resources=True, plans=[free_plan])
        child = organization_factory(parent=parent)

        assert child.get_inherited_plans() == []

    @pytest.mark.django_db()
    def test_get_inherited_plans_recursive_grandparent(
        self, organization_factory, plan_factory
    ):
        """Walks the parent chain when each ancestor shares resources"""
        paid_plan = plan_factory(base_price=100)
        grandparent = organization_factory(share_resources=True, plans=[paid_plan])
        parent = organization_factory(parent=grandparent, share_resources=True)
        child = organization_factory(parent=parent)

        result = child.get_inherited_plans()
        assert result == [(grandparent, paid_plan)]

    @pytest.mark.django_db()
    def test_get_inherited_plans_membership_group(
        self, organization_factory, plan_factory
    ):
        """Returns plan from a membership group that shares resources"""
        paid_plan = plan_factory(base_price=100)
        group = organization_factory(share_resources=True, plans=[paid_plan])
        member_org = organization_factory()
        group.members.add(member_org)

        result = member_org.get_inherited_plans()
        assert result == [(group, paid_plan)]

    @pytest.mark.django_db()
    def test_get_inherited_plans_dedupes_overlapping_sources(
        self, organization_factory, plan_factory
    ):
        """An org reachable via both a group and a parent appears once"""
        paid_plan = plan_factory(base_price=100)
        shared = organization_factory(share_resources=True, plans=[paid_plan])
        # `shared` is both the parent's membership group and the parent's parent
        parent = organization_factory(share_resources=True, parent=shared)
        shared.members.add(parent)
        child = organization_factory(parent=parent)

        result = child.get_inherited_plans()
        assert result == [(shared, paid_plan)]


class TestOrganizationWixSyncIntegration:
    """Integration tests for Wix sync triggers in Organization model"""

    # --- Tests for direct M2M assignment (Bug #637) ---

    @pytest.mark.django_db(transaction=True)
    def test_direct_member_add_triggers_wix_sync(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Directly adding a member org to group.members should trigger Wix sync.

        This reproduces the bug where staff assigns ChildOrg to ParentOrg via
        Django admin (bypassing OrganizationInvitation), and Wix sync is not triggered.
        """
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        member_org = organization_factory(users=[user_factory()])

        # Simulate admin directly assigning ChildOrg to ParentOrg.members
        # (bypasses OrganizationInvitation.accept)
        group.members.add(member_org)

        # Should trigger Wix sync for member org's users via the group's plan
        mock_sync.assert_called_once_with(member_org.pk, group.pk, wix_plan.pk)

    @pytest.mark.django_db(transaction=True)
    def test_direct_member_add_no_sync_when_share_resources_false(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """
        Direct member add should not trigger sync
        when group has share_resources=False
        """
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=False, plans=[wix_plan]
        )
        member_org = organization_factory(users=[user_factory()])

        group.members.add(member_org)

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_direct_member_add_no_sync_when_no_wix_plan(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Direct member add should not trigger sync when group has no Wix plan"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        non_wix_plan = plan_factory(wix=False)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[non_wix_plan]
        )
        member_org = organization_factory(users=[user_factory()])

        group.members.add(member_org)

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_direct_member_add_no_sync_when_no_plan(
        self, organization_factory, user_factory, mocker
    ):
        """Direct member add should not trigger sync when group has no plan at all"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        group = organization_factory(collective_enabled=True, share_resources=True)
        member_org = organization_factory(users=[user_factory()])

        group.members.add(member_org)

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_setting_parent_triggers_wix_sync(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Setting parent FK via admin should trigger Wix sync when parent
        has a Wix plan with share_resources=True."""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        parent = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        child = organization_factory(users=[user_factory()])

        child.parent = parent
        child.save()

        mock_sync.assert_called_once_with(child.pk, parent.pk, wix_plan.pk)

    @pytest.mark.django_db(transaction=True)
    def test_setting_parent_no_sync_when_share_resources_false(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Setting parent FK should not trigger sync when parent has
        share_resources=False."""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        parent = organization_factory(
            collective_enabled=True, share_resources=False, plans=[wix_plan]
        )
        child = organization_factory(users=[user_factory()])

        child.parent = parent
        child.save()

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_setting_parent_no_sync_when_no_wix_plan(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Setting parent FK should not trigger sync when parent has no Wix plan."""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        non_wix_plan = plan_factory(wix=False)
        parent = organization_factory(
            collective_enabled=True, share_resources=True, plans=[non_wix_plan]
        )
        child = organization_factory(users=[user_factory()])

        child.parent = parent
        child.save()

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_saving_without_parent_change_no_sync(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Saving an org that already has a parent should not re-trigger sync."""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        parent = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        child = organization_factory(users=[user_factory()], parent=parent)

        # Reset after factory creation which triggers the signal
        mock_sync.reset_mock()

        # Save without changing parent
        child.save()

        mock_sync.assert_not_called()

    # --- Tests for share_resources toggle (existing behaviour) ---

    @pytest.mark.django_db(transaction=True)
    def test_save_triggers_wix_sync_on_share_resources_toggle(
        self, organization_factory, plan_factory, mocker
    ):
        """Test that toggling share_resources from False to True triggers Wix sync"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=False, plans=[wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        # Toggle share_resources to True
        group.share_resources = True
        group.save()

        mock_sync.assert_called_once_with(member_org.pk, group.pk, wix_plan.pk)

    @pytest.mark.django_db(transaction=True)
    def test_save_no_sync_when_share_resources_already_true(
        self, organization_factory, plan_factory, mocker
    ):
        """Test that save doesn't trigger sync when share_resources was already True"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        # The m2m_changed signal fires sync on the add above; reset to verify
        # the save itself does not trigger additional syncs.
        mock_sync.reset_mock()

        # Save without changing share_resources
        group.save()

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_save_no_sync_when_no_wix_plan(
        self, organization_factory, plan_factory, mocker
    ):
        """Test that toggling share_resources doesn't sync when no Wix plan"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        non_wix_plan = plan_factory(wix=False)
        group = organization_factory(
            collective_enabled=True, share_resources=False, plans=[non_wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        group.share_resources = True
        group.save()

        mock_sync.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_save_syncs_multiple_members_and_children(
        self, organization_factory, plan_factory, mocker
    ):
        """Test that toggling share_resources syncs both members and children"""
        mock_sync = mocker.patch(
            "squarelet.organizations.tasks.sync_wix_for_group_member.delay"
        )
        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=False, plans=[wix_plan]
        )
        member_org1 = organization_factory()
        member_org2 = organization_factory()
        child_org = organization_factory(parent=group)
        group.members.add(member_org1, member_org2)

        group.share_resources = True
        group.save()

        # Should sync all members and children
        assert mock_sync.call_count == 3
        call_args = [call[0] for call in mock_sync.call_args_list]
        member_pks = [args[0] for args in call_args]
        assert member_org1.pk in member_pks
        assert member_org2.pk in member_pks
        assert child_org.pk in member_pks


class TestMultipleSubscriptions:
    """Tests for multi-subscription methods on Organization"""

    @pytest.mark.django_db
    def test_add_subscription_creates_new(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """add_subscription creates a new Subscription for an org with none."""
        org = organization_factory()
        plan = plan_factory()
        user = user_factory()

        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email="test@example.com",
        )

        # Pass payment_method explicitly to skip card detection (avoids Stripe call)
        org.add_subscription(plan, org.max_users, user, payment_method="invoice")

        assert Subscription.objects.filter(organization=org, plan=plan).exists()

    @pytest.mark.django_db
    def test_add_subscription_same_plan_raises(
        self, organization_factory, plan_factory, subscription_factory, user_factory
    ):
        """add_subscription raises ValueError if org already has active sub for plan."""
        org = organization_factory()
        plan = plan_factory()
        user = user_factory()
        subscription_factory(organization=org, plan=plan)

        with pytest.raises(
            SubscriptionError, match="already has an active subscription"
        ):
            org.add_subscription(plan, org.max_users, user)

    @pytest.mark.django_db
    def test_add_subscription_two_different_plans(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """add_subscription allows adding a second plan if it differs."""
        org = organization_factory()
        plan_a = plan_factory()
        plan_b = plan_factory()
        user = user_factory()

        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email="test@example.com",
        )

        # Pass payment_method explicitly to skip card detection (avoids Stripe call)
        org.add_subscription(plan_a, org.max_users, user, payment_method="invoice")
        org.add_subscription(plan_b, org.max_users, user, payment_method="invoice")

        assert Subscription.objects.filter(organization=org).count() == 2

    @pytest.mark.django_db
    def test_add_subscription_none_max_users_uses_plan_minimum(
        self,
        individual_organization_factory,
        plan_factory,
        user_factory,
        mocker,
    ):
        """add_subscription with max_users=None (individual org form omits the field)
        falls back to plan.minimum_users instead of inserting NULL for quantity."""
        org = individual_organization_factory()
        plan = plan_factory(minimum_users=1)
        user = user_factory()

        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            email="test@example.com",
        )

        org.add_subscription(plan, None, user, payment_method="invoice")

        sub = Subscription.objects.get(organization=org, plan=plan)
        assert sub.quantity == plan.minimum_users

    @pytest.mark.django_db
    def test_remove_subscription_by_plan(
        self,
        organization_factory,
        plan_factory,
        subscription_factory,
        user_factory,
        mocker,
    ):
        """remove_subscription by plan cancels that sub and leaves others."""
        org = organization_factory()
        plan_a = plan_factory()
        plan_b = plan_factory()
        user = user_factory()
        sub_a = subscription_factory(organization=org, plan=plan_a)
        sub_b = subscription_factory(organization=org, plan=plan_b)

        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            new_callable=lambda: property(lambda self: None),
        )

        org.remove_subscription(plan_a, user)

        sub_a.refresh_from_db()
        assert sub_a.cancelled
        assert Subscription.objects.filter(pk=sub_b.pk).exists()

    @pytest.mark.django_db
    def test_modify_subscription(
        self,
        organization_factory,
        plan_factory,
        subscription_factory,
        user_factory,
    ):
        """modify_subscription updates the plan on the matching subscription."""
        org = organization_factory()
        plan_a = plan_factory()
        plan_b = plan_factory()
        user = user_factory()
        subscription_factory(organization=org, plan=plan_a)

        org.modify_subscription(plan_a, plan_b, org.max_users, user)

        assert org.subscriptions.filter(plan=plan_b).exists()

    @pytest.mark.django_db
    def test_modify_subscription_missing_plan_raises(
        self, organization_factory, plan_factory, user_factory
    ):
        """modify_subscription raises ValueError if org has no sub for old_plan."""
        org = organization_factory()
        plan_a = plan_factory()
        plan_b = plan_factory()
        user = user_factory()

        with pytest.raises(ValueError, match="does not have an active subscription"):
            org.modify_subscription(plan_a, plan_b, org.max_users, user)

    @pytest.mark.django_db
    def test_has_active_subscription_with_plan_arg(
        self, organization_factory, plan_factory, subscription_factory
    ):
        """has_active_subscription(plan=X) is True for X, False for others."""
        org = organization_factory()
        plan_a = plan_factory()
        plan_b = plan_factory()
        subscription_factory(organization=org, plan=plan_a)

        assert org.has_active_subscription(plan=plan_a)
        assert not org.has_active_subscription(plan=plan_b)

    @pytest.mark.django_db
    def test_has_active_subscription_includes_cancelled(
        self, organization_factory, plan_factory, subscription_factory
    ):
        """cancelled=True means pending cancellation at period end — still active."""
        org = organization_factory()
        plan = plan_factory()
        subscription_factory(organization=org, plan=plan, cancelled=True)

        assert org.has_active_subscription(plan=plan)
        assert org.has_active_subscription()
