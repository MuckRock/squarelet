# Standard Library
from unittest.mock import Mock

# Third Party
import pytest
import stripe

# Squarelet
from .test_invoice import Invoice, create_mock_stripe_invoice

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
