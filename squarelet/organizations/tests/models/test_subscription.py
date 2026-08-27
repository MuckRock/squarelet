# Django
from django.utils.timezone import get_current_timezone

# Standard Library
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import Mock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.models import SubscriptionItem

# Local
from .test_invoice import Invoice, create_mock_stripe_invoice


class TestSubscription:
    """Unit tests for the Subscription model"""

    @pytest.mark.django_db()
    def test_start(self, subscription_item_factory, professional_plan_factory, mocker):
        plan = professional_plan_factory()
        subscription = subscription_item_factory(plan=plan).subscription

        # Mock stripe subscription creation
        stripe_subscription_id = "sub_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id,
            status="active",
            latest_invoice=None,  # No invoice to avoid invoice creation path
        )
        mocked_customer = Mock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mock_sub_service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_service.create.return_value = mock_stripe_subscription
        mock_sub_service.get_current_period_end.return_value = None

        subscription.start()

        mock_sub_service.create.assert_called_with(
            stripe_customer=mocked_customer.stripe_customer,
            items=subscription.stripe_items(),
            billing="charge_automatically",
            metadata={"action": f"Subscription ({subscription.organization})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=False,
        )
        assert subscription.subscription_id == stripe_subscription_id

    @pytest.mark.django_db()
    def test_start_no_auto_renew(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """A plan with auto_renew disabled starts the Stripe subscription with
        cancel_at_period_end=True so it does not automatically renew."""
        # The "Professional" plan is seeded by a data migration, so
        # django_get_or_create (keyed on name) returns that existing row and
        # ignores the auto_renew override passed to the factory. Force it off
        # explicitly so the plan actually has auto_renew disabled.
        plan = professional_plan_factory()
        plan.auto_renew = False
        plan.save()
        subscription = subscription_item_factory(plan=plan).subscription

        period_end_ts = 1_800_000_000
        mock_stripe_subscription = Mock(
            id="sub_test123",
            status="active",
            latest_invoice=None,
        )
        mocked_customer = Mock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.create.return_value = mock_stripe_subscription
        mock_sub_svc.get_current_period_end.return_value = period_end_ts

        subscription.start()

        mock_sub_svc.create.assert_called_with(
            stripe_customer=mocked_customer.stripe_customer,
            items=subscription.stripe_items(),
            billing="charge_automatically",
            metadata={"action": f"Subscription ({subscription.organization})"},
            days_until_due=None,
            anchor_day=None,
            cancel_at_period_end=True,
        )
        expected_date = datetime.fromtimestamp(
            period_end_ts, tz=get_current_timezone()
        ).date()
        assert subscription.cancel_at == expected_date

    @pytest.mark.django_db()
    def test_start_existing(self, subscription_item_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_item_factory().subscription
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        subscription.start()
        mocked.subscription_items.create.assert_not_called()

    @pytest.mark.django_db()
    def test_start_free(self, subscription_item_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_item_factory().subscription
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        subscription.start()
        mocked.subscription_items.create.assert_not_called()

    @pytest.mark.django_db()
    def test_cancel(self, subscription_item_factory, mocker):
        subscription = subscription_item_factory().subscription
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        mocked_stripe_subscription.id = "sub_test123"
        period_end_ts = 1_800_000_000
        mock_updated = mocker.MagicMock(status="active")
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.cancel_at_period_end.return_value = mock_updated
        mock_sub_svc.get_current_period_end.return_value = period_end_ts
        subscription.cancel()
        mock_sub_svc.cancel_at_period_end.assert_called_once_with(
            mocked_stripe_subscription,
        )
        assert subscription.cancelled

        expected_date = datetime.fromtimestamp(
            period_end_ts, tz=get_current_timezone()
        ).date()
        assert subscription.cancel_at == expected_date
        mocked_save.assert_called()

    @pytest.mark.django_db()
    def test_cancel_no_stripe_subscription(self, subscription_item_factory, mocker):
        """cancel_at stays None when there is no Stripe subscription (free plan)."""
        subscription = subscription_item_factory().subscription
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            new=None,
        )
        subscription.cancel()
        assert subscription.cancelled
        assert subscription.cancel_at is None
        mocked_save.assert_called()

    @pytest.mark.django_db()
    def test_start_creates_invoice_with_card(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """Test that subscription.start() creates an Invoice record for card payment"""
        plan = professional_plan_factory()
        subscription = subscription_item_factory(plan=plan).subscription

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_test123"
        stripe_invoice_id = "in_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, status="active", latest_invoice=stripe_invoice_id
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
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.create.return_value = mock_stripe_subscription
        mock_sub_svc.get_current_period_end.return_value = None
        mock_provider.get_invoice_service.return_value.retrieve.return_value = (
            mock_stripe_invoice
        )
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
        self, subscription_item_factory, plan_factory, mocker
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
        subscription = subscription_item_factory(
            plan=plan, subscription__interval="annual"
        ).subscription

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_annual123"
        stripe_invoice_id = "in_annual123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, status="active", latest_invoice=stripe_invoice_id
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
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.create.return_value = mock_stripe_subscription
        mock_sub_svc.get_current_period_end.return_value = None
        mock_provider.get_invoice_service.return_value.retrieve.return_value = (
            mock_stripe_invoice
        )

        # Start the subscription with invoice payment
        subscription.start(payment_method="invoice")

        # Verify subscription was created with send_invoice billing
        mock_provider.get_subscription_service.return_value.create.assert_called_with(
            stripe_customer=mocked_customer.stripe_customer,
            items=subscription.stripe_items(),
            billing="send_invoice",
            metadata={"action": f"Subscription ({subscription.organization})"},
            days_until_due=30,
            anchor_day=None,
            cancel_at_period_end=False,
        )

        # Verify Invoice record was created
        invoice = Invoice.objects.filter(invoice_id=stripe_invoice_id).first()
        assert invoice is not None
        assert invoice.organization == subscription.organization
        assert invoice.subscription == subscription
        assert invoice.due_date is not None

    @pytest.mark.django_db()
    def test_start_free_plan_no_invoice(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """Test that free plans don't create invoices"""
        mocker.patch("stripe.Plan.create")
        plan = plan_factory()  # Free plan (no base_price = free)
        subscription = subscription_item_factory(plan=plan).subscription

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
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """Test that subscription still succeeds if invoice retrieval fails"""
        plan = professional_plan_factory()
        subscription = subscription_item_factory(plan=plan).subscription

        # Mock Stripe subscription creation
        stripe_subscription_id = "sub_test123"
        mock_stripe_subscription = Mock(
            id=stripe_subscription_id, status="active", latest_invoice="in_test123"
        )

        mocked_customer = Mock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked_customer,
        )
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.create.return_value = mock_stripe_subscription
        mock_sub_svc.get_current_period_end.return_value = None
        mock_provider.get_invoice_service.return_value.retrieve.side_effect = (
            stripe.InvalidRequestError("No such invoice", "invoice")
        )

        # Start should still succeed
        subscription.start(payment_method="card")

        # Verify subscription was still created
        assert subscription.subscription_id == stripe_subscription_id

        # Invoice won't be created due to error (webhook will handle it)
        assert Invoice.objects.count() == 0

    @pytest.mark.django_db()
    def test_start_caches_stripe_status(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """start() caches stripe_status and current_period_end from Stripe response"""

        plan = professional_plan_factory()
        subscription = subscription_item_factory(plan=plan).subscription

        period_end_ts = 1800000000
        mock_stripe_sub = Mock(
            id="sub_cached",
            status="active",
            latest_invoice=None,
        )
        mock_items_data = Mock()
        mock_items_data.current_period_end = period_end_ts
        mock_stripe_sub.items.data = [mock_items_data]

        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=Mock(),
        )
        mock_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value
        mock_sub_svc = mock_provider.get_subscription_service.return_value
        mock_sub_svc.create.return_value = mock_stripe_sub
        mock_sub_svc.get_current_period_end.return_value = period_end_ts

        subscription.start()

        subscription.refresh_from_db()
        assert subscription.stripe_status == "active"
        assert (
            subscription.current_period_end
            == datetime.fromtimestamp(
                period_end_ts,
                tz=dt_timezone.utc,
            ).astimezone()
        )

    @pytest.mark.django_db()
    def test_stripe_modify_sends_every_line(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """stripe_modify pushes all of the subscription's lines, with their ids."""
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_mod",
            stripe_item_id="si_mod",
        )
        subscription = item.subscription
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_svc.modify.return_value = Mock(status="active")
        mock_sub_svc.get_current_period_end.return_value = None
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")

        subscription.stripe_modify()

        assert subscription.cancel_at is None
        mock_sub_svc.modify.assert_called_with(
            "sub_mod",
            cancel_at_period_end=False,
            items=[
                {
                    "id": "si_mod",
                    "plan": item.plan.stripe_id,
                    "quantity": item.quantity,
                }
            ],
            billing="charge_automatically",
            metadata={"action": f"Subscription ({subscription.organization})"},
            days_until_due=None,
        )

    @pytest.mark.django_db()
    def test_stripe_modify_no_auto_renew(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """A plan with auto_renew off flags the Stripe subscription to end."""
        plan = professional_plan_factory()
        plan.auto_renew = False
        plan.save()
        item = subscription_item_factory(
            plan=plan, subscription__subscription_id="sub_norenew"
        )
        period_end_ts = 1_800_000_000
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mock_sub_svc.modify.return_value = Mock(status="active")
        mock_sub_svc.get_current_period_end.return_value = period_end_ts
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")

        item.subscription.stripe_modify()

        assert mock_sub_svc.modify.call_args.kwargs["cancel_at_period_end"] is True
        expected_date = datetime.fromtimestamp(
            period_end_ts, tz=get_current_timezone()
        ).date()
        assert item.subscription.cancel_at == expected_date

    @pytest.mark.django_db()
    def test_cancel_flags_every_line(self, subscription_item_factory, plan_factory):
        """The UI lists lines, so a line must report a whole-sub cancellation."""
        item = subscription_item_factory()
        other = subscription_item_factory(
            subscription=item.subscription, plan=plan_factory(name="Other Plan")
        )
        subscription = item.subscription
        subscription.current_period_end = datetime(2026, 9, 20, tzinfo=dt_timezone.utc)
        subscription.save()

        subscription.cancel()

        for line in (item, other):
            line.refresh_from_db()
            assert line.cancelled
            assert line.cancel_at == date(2026, 9, 20)

    @pytest.mark.django_db()
    def test_uncancel_clears_every_line(self, subscription_item_factory, mocker):
        item = subscription_item_factory()
        subscription = item.subscription
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=mocker.Mock(stripe_payment_method_id="pm_test"),
        )
        subscription.cancel()
        subscription.uncancel()

        item.refresh_from_db()
        assert not item.cancelled
        assert item.cancel_at is None

    @pytest.mark.django_db()
    def test_cancelling_each_line_in_turn_cancels_the_subscription(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """The second cancel is the last *active* line, so the sub goes too."""
        first = subscription_item_factory()
        second = subscription_item_factory(
            subscription=first.subscription, plan=plan_factory(name="Second Plan")
        )
        mocked_cancel = mocker.patch(
            "squarelet.organizations.models.Subscription.cancel"
        )

        first.cancel()
        mocked_cancel.assert_not_called()

        second.cancel()
        mocked_cancel.assert_called_once()

    @pytest.mark.django_db()
    def test_uncancelling_a_line_revives_a_cancelled_subscription(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """Reviving a line has to clear Stripe's cancel_at_period_end too."""
        item = subscription_item_factory()
        subscription_item_factory(
            subscription=item.subscription, plan=plan_factory(name="Second Plan")
        )
        mocker.patch(
            "squarelet.organizations.models.Organization.customer",
            return_value=mocker.Mock(stripe_payment_method_id="pm_test"),
        )
        item.subscription.cancel()
        item.refresh_from_db()
        assert item.cancelled

        mocked_uncancel = mocker.patch(
            "squarelet.organizations.models.Subscription.uncancel"
        )
        item.uncancel()
        mocked_uncancel.assert_called_once()

    @pytest.mark.django_db()
    def test_uncancelling_one_line_leaves_the_others_alone(
        self, subscription_item_factory, plan_factory
    ):
        """A line cancelled on its own is revived on its own."""
        first = subscription_item_factory()
        second = subscription_item_factory(
            subscription=first.subscription, plan=plan_factory(name="Second Plan")
        )
        first.cancel()
        first.uncancel()

        first.refresh_from_db()
        second.refresh_from_db()
        assert not first.cancelled
        assert not second.cancelled
        assert not first.subscription.cancelled


class TestSubscriptionItem:
    """Unit tests for the SubscriptionItem model"""

    def test_str(self, subscription_item_factory):
        subscription = subscription_item_factory.build()
        assert (
            str(subscription) == f"SubscriptionItem: {subscription.organization} to "
            f"{subscription.plan.name}"
        )

    def test_stripe_subscription(self, subscription_factory, mocker):
        mocked = mocker.patch("stripe.Subscription.retrieve")
        stripe_subscription = "stripe_subscription"
        mocked.return_value = stripe_subscription
        subscription = subscription_factory.build(subscription_id="subscription_id")
        assert subscription.stripe_subscription == stripe_subscription

    def test_stripe_subscription_empty(self, subscription_factory):
        subscription = subscription_factory.build()
        assert subscription.stripe_subscription is None

    @pytest.mark.django_db()
    def test_modify_pushes_the_new_plan_to_stripe(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """Changing a line's plan saves it and re-syncs the whole subscription."""
        item = subscription_item_factory()
        plan = professional_plan_factory()
        mocked_modify = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_modify"
        )
        item.modify(plan)
        item.refresh_from_db()
        assert item.plan == plan
        mocked_modify.assert_called_once()

    @pytest.mark.django_db()
    def test_cancel_last_item_cancels_the_subscription(
        self, subscription_item_factory, mocker
    ):
        """The only line left cancels the whole subscription at period end."""
        item = subscription_item_factory()
        mocked_cancel = mocker.patch(
            "squarelet.organizations.models.Subscription.cancel"
        )
        item.cancel()
        mocked_cancel.assert_called_once()
        assert SubscriptionItem.objects.filter(pk=item.pk).exists()

    @pytest.mark.django_db()
    def test_cancel_one_of_several_items_flags_it_for_period_end(
        self, subscription_item_factory, plan_factory, mocker
    ):
        """The line keeps billing until the period ends, like a cancelled sub."""
        item = subscription_item_factory(
            subscription__subscription_id="sub_multi", stripe_item_id="si_one"
        )
        period_end = datetime(2026, 9, 20, tzinfo=dt_timezone.utc)
        item.subscription.current_period_end = period_end
        item.subscription.save()
        subscription_item_factory(
            subscription=item.subscription, plan=plan_factory(name="Second Plan")
        )
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value

        item.cancel()

        item.refresh_from_db()
        assert item.cancelled
        assert item.cancel_at == period_end.date()
        # Still on Stripe, and still on the invoice, until the period ends
        mock_sub_svc.modify.assert_not_called()
        assert SubscriptionItem.objects.filter(pk=item.pk).exists()

    @pytest.mark.django_db()
    def test_uncancel_item_clears_the_pending_cancellation(
        self, subscription_item_factory, plan_factory
    ):
        item = subscription_item_factory(subscription__subscription_id="sub_multi")
        subscription_item_factory(
            subscription=item.subscription, plan=plan_factory(name="Second Plan")
        )
        item.cancel()
        item.uncancel()

        item.refresh_from_db()
        assert not item.cancelled
        assert item.cancel_at is None

    @pytest.mark.django_db()
    def test_remove_from_stripe_drops_the_line_without_proration(
        self, subscription_item_factory, mocker
    ):
        """The line was paid for through the period, so no credit is issued."""
        item = subscription_item_factory(
            subscription__subscription_id="sub_multi", stripe_item_id="si_one"
        )
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        mock_sub_svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value

        item.remove_from_stripe()

        mock_sub_svc.modify.assert_called_once_with(
            "sub_multi",
            items=[{"id": "si_one", "deleted": True}],
            proration_behavior="none",
        )
        assert not SubscriptionItem.objects.filter(pk=item.pk).exists()
