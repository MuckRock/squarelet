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
from squarelet.organizations.payments.exceptions import SubscriptionError

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
        assert subscription.cancelled
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
        # Midday, so converting to local time cannot move the date and this
        # test stays about flagging the lines.
        subscription.current_period_end = datetime(
            2026, 9, 20, 12, tzinfo=dt_timezone.utc
        )
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
    def test_auto_renew_survives_one_non_renewing_line(
        self, subscription_item_factory, plan_factory
    ):
        """A non-renewing plan must not drag the renewing lines down."""
        renewing = subscription_item_factory()
        # django_get_or_create keys on name, so the flag is set after creation
        once = plan_factory(name="One Off Plan")
        once.auto_renew = False
        once.save()
        subscription_item_factory(subscription=renewing.subscription, plan=once)

        assert renewing.subscription.auto_renew

    @pytest.mark.django_db()
    def test_auto_renew_false_when_every_line_stops(
        self, subscription_item_factory, plan_factory
    ):
        once = plan_factory(name="One Off Plan")
        once.auto_renew = False
        once.save()
        item = subscription_item_factory(plan=once)

        assert not item.subscription.auto_renew

    @pytest.mark.django_db()
    def test_auto_renew_with_no_lines(self, subscription_factory):
        """An empty subscription must not read as cancelling."""
        assert subscription_factory().auto_renew


class TestSubscriptionNextDate:
    """The renewal date shown on the billing pages."""

    @pytest.mark.django_db()
    def test_next_date_is_local(self, subscription_factory):
        """The date shown is the local one, not the UTC one.

        A period ending just after midnight UTC is still the previous
        evening in the project timezone, and that is the date the customer
        should see.
        """
        subscription = subscription_factory(
            current_period_end=datetime(2026, 9, 21, 2, 0, tzinfo=dt_timezone.utc)
        )
        assert subscription.next_date == date(2026, 9, 20)

    @pytest.mark.django_db()
    def test_next_date_without_a_cached_period(self, subscription_factory):
        assert subscription_factory(current_period_end=None).next_date is None

    @pytest.mark.django_db()
    def test_next_date_does_not_call_stripe(self, subscription_factory, mocker):
        """It reads the cached field - one page view must not fan out to Stripe."""
        mocked_provider = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        )
        subscription = subscription_factory(
            current_period_end=datetime(2026, 9, 21, 12, 0, tzinfo=dt_timezone.utc)
        )
        assert subscription.next_date == date(2026, 9, 21)
        mocked_provider.assert_not_called()


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
        """A paid line changing plan updates the existing subscription."""
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_live",
        )
        plan = professional_plan_factory(name="Other Paid", base_price=30)
        # `modify` identifies the line on Stripe before changing its
        # plan; nothing here is exercising that.
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            None,
        )
        mocked_modify = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_modify"
        )

        item.modify(plan)

        item.refresh_from_db()
        assert item.plan == plan
        mocked_modify.assert_called_once()

    @pytest.mark.django_db()
    def test_upgrading_off_a_free_plan_starts_billing(
        self, subscription_item_factory, plan_factory, professional_plan_factory, mocker
    ):
        """The one that was silently free.

        An organization on a free plan has no Stripe subscription, and
        `stripe_modify` no-ops without one - so the upgrade granted paid
        access and never charged for it.
        """
        item = subscription_item_factory(
            plan=plan_factory(name="Free Tier", base_price=0, price_per_user=0),
            subscription__subscription_id="",
        )
        started = mocker.patch("squarelet.organizations.models.Subscription.start")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_modify")

        item.modify(professional_plan_factory())

        started.assert_called_once()

    @pytest.mark.django_db()
    def test_downgrading_to_a_free_plan_stops_billing(
        self, subscription_item_factory, plan_factory, professional_plan_factory, mocker
    ):
        """The other half, and the worse one.

        Without this the Stripe subscription survives the downgrade and the
        customer keeps being charged for a free plan.
        """
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        item = subscription_item_factory(
            plan=professional_plan_factory(), subscription__subscription_id="sub_live"
        )

        item.modify(plan_factory(name="Free Tier", base_price=0, price_per_user=0))

        service.delete.assert_called_once()
        item.subscription.refresh_from_db()
        assert item.subscription.subscription_id == ""

    @pytest.mark.django_db()
    def test_changing_to_a_different_interval_is_refused(
        self, subscription_item_factory, professional_plan_factory, plan_factory
    ):
        """Stripe will not carry both intervals on one subscription.

        Pushed anyway, it rejects the whole call - so the line has to move
        to the organization's subscription for the other interval, which is
        a remove and an add rather than an edit.
        """
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_monthly",
            subscription__interval="monthly",
        )
        annual = plan_factory(name="Annual Plan", annual=True, base_price=300)

        with pytest.raises(SubscriptionError, match="bills annual"):
            item.modify(annual)

        item.refresh_from_db()
        assert item.plan != annual

    @pytest.mark.django_db()
    def test_the_end_date_agrees_with_the_renewal_date(
        self, subscription_item_factory, mocker
    ):
        """Both read the same field, so both must read it the same way.

        `next_date` converts to local time; `cancel_at` did not, and a
        period ending after 20:00 local is the next day in UTC.  The card
        said the plan ended the day after it renewed.
        """
        item = subscription_item_factory(subscription__subscription_id="sub_tz")
        subscription = item.subscription
        # As it comes back from the database: UTC-aware, an hour past
        # midnight, which is the previous evening in America/New_York.
        subscription.current_period_end = datetime(
            2026, 10, 20, 1, 0, tzinfo=dt_timezone.utc
        )
        subscription.save()
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.cancel_at_period_end.return_value = None
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")

        subscription.cancel()

        assert subscription.cancel_at == subscription.next_date
        assert subscription.cancel_at == date(2026, 10, 19)

    @pytest.mark.django_db()
    def test_downgrading_still_works_when_stripe_has_already_lost_it(
        self, subscription_item_factory, plan_factory, professional_plan_factory, mocker
    ):
        """A subscription cancelled in the Stripe dashboard retrieves as None.

        Deleting None raised, so the local record went on naming a
        subscription Stripe had already forgotten and every retry of the
        downgrade failed the same way.
        """
        item = subscription_item_factory(
            plan=professional_plan_factory(), subscription__subscription_id="sub_gone"
        )
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )

        item.modify(plan_factory(name="Free Tier", base_price=0, price_per_user=0))

        service.delete.assert_not_called()
        item.subscription.refresh_from_db()
        assert item.subscription.subscription_id == ""

    @pytest.mark.django_db()
    def test_a_free_line_is_not_described_to_stripe(
        self, subscription_item_factory, plan_factory, professional_plan_factory
    ):
        """A free plan has no Stripe Plan behind it.

        Naming one would reference an object that does not exist and fail
        the whole call - taking the paid lines alongside it down too.
        """
        paid = subscription_item_factory(
            plan=professional_plan_factory(), subscription__subscription_id="sub_live"
        )
        subscription_item_factory(
            subscription=paid.subscription,
            plan=plan_factory(name="Free Tier", base_price=0, price_per_user=0),
        )

        specs = paid.subscription.stripe_items()

        assert len(specs) == 1
        assert specs[0]["plan"] == paid.plan.stripe_id

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


@pytest.mark.django_db()
class TestLinesAreIdentifiedBeforeTheyAreDescribed:
    """A line with no Stripe id is a request to *add* a line.

    Everything that predates the subscription/item split has an empty
    `stripe_item_id` - the column was added empty and the data migration had
    nothing to fill it from - so the first modify of any existing
    subscription was rejected: "a new item with Price X can't be added
    because an existing Subscription Item is already using that Price".
    """

    def _stripe_sub(self, price_id, item_id="si_existing"):
        return {
            "items": {"data": [{"id": item_id, "price": {"id": price_id}}]},
            "status": "active",
        }

    def test_a_blank_id_is_filled_in_before_the_modify(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_live",
            stripe_item_id="",
        )
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            self._stripe_sub(item.plan.stripe_id),
        )
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.modify.return_value = None

        item.subscription.stripe_modify()

        # The id has to reach Stripe on *this* call, not the next one.
        sent = service.modify.call_args.kwargs["items"]
        assert sent == [
            {
                "plan": item.plan.stripe_id,
                "quantity": item.quantity,
                "id": "si_existing",
            }
        ]
        item.refresh_from_db()
        assert item.stripe_item_id == "si_existing"

    def test_an_unknown_price_is_left_alone(
        self, subscription_item_factory, professional_plan_factory, mocker
    ):
        """No match on Stripe means no id to invent - the line is genuinely new."""
        item = subscription_item_factory(
            plan=professional_plan_factory(),
            subscription__subscription_id="sub_live",
            stripe_item_id="",
        )
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            self._stripe_sub("price_something_else"),
        )
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        service.modify.return_value = None

        item.subscription.stripe_modify()

        assert "id" not in service.modify.call_args.kwargs["items"][0]
        item.refresh_from_db()
        assert item.stripe_item_id == ""
