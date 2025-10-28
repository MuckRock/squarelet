# Django
from django.test import override_settings
from django.utils import timezone

# Standard Library
from datetime import date, timedelta

# Third Party
import pytest
import stripe
from dateutil.relativedelta import relativedelta

# Squarelet
from squarelet.organizations import tasks
from squarelet.organizations.models import Charge, Invoice, Subscription
from squarelet.organizations.tests.factories import InvoiceFactory, SubscriptionFactory


@pytest.mark.django_db()
def test_restore_organization(organization_plan_factory, mocker):
    patched = mocker.patch("squarelet.organizations.tasks.send_cache_invalidations")
    mocker.patch("stripe.Plan.create")
    today = date.today()
    organization_plan = organization_plan_factory()

    subsc_update_cancel = SubscriptionFactory(
        update_on=today - timedelta(1), plan=organization_plan, cancelled=True
    )
    subsc_update_later = SubscriptionFactory(
        update_on=today + timedelta(1), plan=organization_plan
    )
    subsc_update = SubscriptionFactory(
        update_on=today - timedelta(1), plan=organization_plan
    )

    tasks.restore_organization()

    subsc_update_later.refresh_from_db()
    subsc_update.refresh_from_db()

    # update cancel should have been deleted
    assert not Subscription.objects.filter(pk=subsc_update_cancel.pk).exists()

    # update later should have not been changed
    assert subsc_update_later.plan == organization_plan
    assert subsc_update_later.update_on == today + timedelta(1)

    assert subsc_update.plan == organization_plan
    assert subsc_update.update_on == today + relativedelta(months=1)

    assert patched.call_args[0][0] == "organization"
    assert set(patched.call_args[0][1]) == set(
        [subsc_update.organization.uuid, subsc_update_cancel.organization.uuid]
    )


class TestHandleChargeSucceeded:
    """Unit tests for the handle_charge_succeeded task"""

    @pytest.mark.django_db()
    def test_with_invoice(self, organization_factory, mocker):
        timestamp = timezone.now().replace(microsecond=0)
        charge_data = {
            "amount": 2500,
            "created": int(timestamp.timestamp()),
            "customer": "cus_Bp0Alb14pfVB9D",
            "description": "Payment for invoice E28A672-0040",
            "id": "ch_EwJiGXbaafREhT",
            "invoice": "in_EwIgmFCn7cnZFB",
            "metadata": {},
            "object": "charge",
        }
        organization = organization_factory(
            customer__customer_id=charge_data["customer"]
        )
        invoice = {
            "id": "in_EwIgmFCn7cnZFB",
            "lines": {
                "data": [
                    {
                        "amount": 2500,
                        "plan": {"id": "org", "product": "prod_BTLmRCZ5cpxsPH"},
                    }
                ]
            },
        }
        product = {"name": "Organization"}
        mocker.patch(
            "squarelet.organizations.tasks.stripe.Invoice.retrieve",
            return_value=invoice,
        )
        mocker.patch(
            "squarelet.organizations.tasks.stripe.Product.retrieve",
            return_value=product,
        )
        mocked = mocker.patch("squarelet.organizations.models.Charge.send_receipt")

        tasks.handle_charge_succeeded(charge_data)

        charge = Charge.objects.get(charge_id=charge_data["id"])
        assert charge.amount == charge_data["amount"]
        assert charge.fee_amount == 0
        assert charge.organization == organization
        assert charge.created_at == timestamp
        assert charge.description == f"Subscription Payment for {product['name']} plan"
        mocked.assert_called_once()

    @pytest.mark.django_db()
    def test_without_invoice(self, organization_factory, mocker):
        timestamp = timezone.now().replace(microsecond=0)
        charge_data = {
            "amount": 2500,
            "created": int(timestamp.timestamp()),
            "customer": "cus_Bp0Alb14pfVB9D",
            "description": "Payment for request #123",
            "id": "ch_EwJiGXbaafREhT",
            "invoice": None,
            "metadata": {},
            "object": "charge",
        }
        organization = organization_factory(
            customer__customer_id=charge_data["customer"]
        )
        mocked = mocker.patch("squarelet.organizations.models.Charge.send_receipt")

        tasks.handle_charge_succeeded(charge_data)

        charge = Charge.objects.get(charge_id=charge_data["id"])
        assert charge.amount == charge_data["amount"]
        assert charge.fee_amount == 0
        assert charge.organization == organization
        assert charge.created_at == timestamp
        assert charge.description == charge_data["description"]
        mocked.assert_called_once()

    def test_without_customer(self):
        timestamp = timezone.now().replace(microsecond=0)
        charge_data = {
            "amount": 2500,
            "created": int(timestamp.timestamp()),
            "customer": None,
            "description": "Payment for request #123",
            "id": "ch_EwJiGXbaafREhT",
            "invoice": None,
            "metadata": {},
            "object": "charge",
        }

        tasks.handle_charge_succeeded(charge_data)

    def test_crowdfund(self):
        timestamp = timezone.now().replace(microsecond=0)
        charge_data = {
            "amount": 2500,
            "created": int(timestamp.timestamp()),
            "customer": "cus_Bp0Alb14pfVB9D",
            "description": "Payment for request #123",
            "id": "ch_EwJiGXbaafREhT",
            "invoice": None,
            "metadata": {"action": "crowdfund-payment"},
            "object": "charge",
        }

        tasks.handle_charge_succeeded(charge_data)

    def test_recurring_donation(self, mocker):
        timestamp = timezone.now().replace(microsecond=0)
        charge_data = {
            "amount": 2500,
            "created": int(timestamp.timestamp()),
            "customer": "cus_Bp0Alb14pfVB9D",
            "description": "Payment for invoice E28A672-0040",
            "id": "ch_EwJiGXbaafREhT",
            "invoice": "in_EwIgmFCn7cnZFB",
            "metadata": {},
            "object": "charge",
        }
        invoice = {
            "id": "in_EwIgmFCn7cnZFB",
            "lines": {
                "data": [
                    {
                        "amount": 2500,
                        "plan": {"id": "donate", "product": "prod_BTLmRCZ5cpxsPH"},
                    }
                ]
            },
        }
        mocker.patch(
            "squarelet.organizations.tasks.stripe.Invoice.retrieve",
            return_value=invoice,
        )
        mocker.patch(
            "squarelet.organizations.tasks.stripe.Product.retrieve",
            return_value={"name": "Professional"},
        )

        tasks.handle_charge_succeeded(charge_data)


@pytest.mark.django_db()
def test_handle_invoice_failed(organization_factory, user_factory, mailoutbox):
    user = user_factory()
    customer_id = "cus_123"
    organization = organization_factory(
        admins=[user], customer__customer_id=customer_id
    )
    invoice_data = {"id": 1, "customer": customer_id, "attempt_count": 2}
    tasks.handle_invoice_failed(invoice_data)
    organization.refresh_from_db()
    assert organization.payment_failed
    mail = mailoutbox[0]
    assert mail.subject == "Your payment has failed"
    assert mail.to == [user.email]


class TestHandleInvoiceCreated:
    """Unit tests for the handle_invoice_created task"""

    @pytest.mark.django_db(transaction=True)
    def test_creates_invoice(self, organization_factory, subscription_factory):
        timestamp = timezone.now().replace(microsecond=0)
        due_timestamp = (timestamp + timedelta(days=30)).replace(microsecond=0)
        organization = organization_factory(customer__customer_id="cus_123")
        subscription = subscription_factory(
            organization=organization, subscription_id="sub_123"
        )

        invoice_data = {
            "id": "in_123",
            "customer": "cus_123",
            "parent": {
                "type": "subscription_details",
                "subscription_details": {"subscription": "sub_123"},
            },
            "amount_due": 10000,
            "due_date": int(due_timestamp.timestamp()),
            "status": "draft",
            "created": int(timestamp.timestamp()),
        }

        tasks.handle_invoice_created(invoice_data)

        invoice = Invoice.objects.get(invoice_id="in_123")
        assert invoice.organization == organization
        assert invoice.subscription == subscription
        assert invoice.amount == 10000
        assert invoice.status == "draft"

    @pytest.mark.django_db(transaction=True)
    def test_handles_missing_subscription(self, organization_factory):
        timestamp = timezone.now().replace(microsecond=0)
        organization_factory(customer__customer_id="cus_123")

        invoice_data = {
            "id": "in_123",
            "customer": "cus_123",
            "parent": {
                "type": "subscription_details",
                "subscription_details": {"subscription": "no_match"},
            },
            "amount_due": 10000,
            "due_date": None,
            "status": "draft",
            "created": int(timestamp.timestamp()),
        }

        tasks.handle_invoice_created(invoice_data)

        # Refresh from database to ensure we have the committed state
        invoice = Invoice.objects.get(invoice_id="in_123")
        assert invoice.subscription is None

    @pytest.mark.django_db(transaction=True)
    def test_updates_existing_invoice(self, organization_factory):
        timestamp = timezone.now().replace(microsecond=0)
        organization = organization_factory(customer__customer_id="cus_123")
        existing_invoice = InvoiceFactory(
            invoice_id="in_123", organization=organization, amount=5000
        )

        invoice_data = {
            "id": "in_123",
            "customer": "cus_123",
            "subscription": None,
            "amount_due": 10000,
            "due_date": None,
            "status": "open",
            "created": int(timestamp.timestamp()),
        }

        tasks.handle_invoice_created(invoice_data)

        existing_invoice.refresh_from_db()
        assert existing_invoice.amount == 10000
        assert existing_invoice.status == "open"


class TestHandleInvoiceFinalized:
    """Unit tests for the handle_invoice_finalized task"""

    @pytest.mark.django_db
    def test_updates_invoice_status(self, invoice_factory):
        timestamp = timezone.now().replace(microsecond=0)
        due_timestamp = (timestamp + timedelta(days=30)).replace(microsecond=0)
        invoice = invoice_factory(invoice_id="in_123", status="draft", due_date=None)

        invoice_data = {
            "id": "in_123",
            "status": "open",
            "due_date": int(due_timestamp.timestamp()),
        }

        tasks.handle_invoice_finalized(invoice_data)

        invoice.refresh_from_db()
        assert invoice.status == "open"
        assert invoice.due_date == due_timestamp.date()


class TestHandleInvoicePaymentSucceeded:
    """Unit tests for the handle_invoice_payment_succeeded task"""

    @pytest.mark.django_db
    def test_marks_invoice_paid(self, invoice_factory):
        invoice = invoice_factory(invoice_id="in_123", status="open")

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_payment_succeeded(invoice_data)

        invoice.refresh_from_db()
        assert invoice.status == "paid"

    @pytest.mark.django_db
    def test_clears_payment_failed_flag(self, organization_factory, invoice_factory):
        organization = organization_factory(payment_failed=True)
        invoice_factory(invoice_id="in_123", organization=organization, status="open")

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_payment_succeeded(invoice_data)

        organization.refresh_from_db()
        assert organization.payment_failed is False

    @pytest.mark.django_db
    def test_does_not_change_flag_if_already_false(
        self, organization_factory, invoice_factory
    ):
        organization = organization_factory(payment_failed=False)
        invoice_factory(invoice_id="in_123", organization=organization, status="open")

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_payment_succeeded(invoice_data)

        organization.refresh_from_db()
        assert organization.payment_failed is False


class TestHandleInvoiceMarkedUncollectible:
    """Unit tests for the handle_invoice_marked_uncollectible task"""

    @pytest.mark.django_db
    def test_marks_invoice_uncollectible(self, invoice_factory):
        invoice = invoice_factory(invoice_id="in_123", status="open")

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_marked_uncollectible(invoice_data)

        invoice.refresh_from_db()
        assert invoice.status == "uncollectible"


class TestHandleInvoiceVoided:
    """Unit tests for the handle_invoice_voided task"""

    @pytest.mark.django_db
    def test_marks_invoice_void(self, invoice_factory):
        invoice = invoice_factory(invoice_id="in_123", status="open")

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_voided(invoice_data)

        invoice.refresh_from_db()
        assert invoice.status == "void"


class TestCheckOverdueInvoices:
    """Unit tests for the check_overdue_invoices task"""

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_sets_payment_failed_for_overdue_within_grace_period(
        self, invoice_factory, organization_factory, mocker
    ):
        """Invoices overdue within grace period should set payment_failed
        and send warning"""
        org = organization_factory()
        # Invoice 20 days overdue (within 30-day grace period)
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=20),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should set payment_failed flag
        org.refresh_from_db()
        assert org.payment_failed

        # Should send overdue warning email
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_overdue.html"
        assert call_kwargs["extra_context"]["invoice"] == invoice
        assert call_kwargs["extra_context"]["days_overdue"] == 20
        assert call_kwargs["extra_context"]["days_until_cancellation"] == 10

    @pytest.mark.django_db(transaction=True)
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_cancels_at_grace_period_threshold(
        self, invoice_factory, organization_factory, subscription_factory, mocker
    ):
        """Invoice exactly at grace period threshold should cancel subscription"""
        org = organization_factory()
        subscription = subscription_factory(organization=org)
        invoice = invoice_factory(
            organization=org,
            subscription=subscription,
            status="open",
            due_date=date.today() - timedelta(days=30),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")
        mocker.patch("stripe.Invoice.modify")
        mock_subscription_cancelled = mocker.patch(
            "squarelet.organizations.models.Organization.subscription_cancelled"
        )

        tasks.process_overdue_invoice(invoice.id)

        # Should cancel subscription
        mock_subscription_cancelled.assert_called_once()

        # Should send cancellation email
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_cancelled.html"
        assert call_kwargs["extra_context"]["invoice"] == invoice
        assert call_kwargs["extra_context"]["days_overdue"] == 30

    @pytest.mark.django_db(transaction=True)
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_does_not_resend_email_if_payment_failed_already_set(
        self, invoice_factory, organization_factory, subscription_factory, mocker
    ):
        """Should not resend overdue email if payment_failed flag is already
        set (still cancels at threshold)"""
        org = organization_factory(payment_failed=True)
        subscription = subscription_factory(organization=org)
        invoice = invoice_factory(
            organization=org,
            subscription=subscription,
            status="open",
            due_date=date.today() - timedelta(days=30),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")
        mocker.patch("stripe.Invoice.modify")

        tasks.process_overdue_invoice(invoice.id)

        # At threshold, should cancel and send cancellation email (not overdue email)
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_cancelled.html"

    @pytest.mark.django_db(transaction=True)
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_cancels_subscription_past_grace_period(
        self, invoice_factory, organization_factory, subscription_factory, mocker
    ):
        """Invoice past grace period should cancel subscription"""
        org = organization_factory()
        subscription = subscription_factory(organization=org)
        invoice = invoice_factory(
            organization=org,
            subscription=subscription,
            status="open",
            due_date=date.today() - timedelta(days=35),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")
        mock_stripe = mocker.patch("stripe.Invoice.modify")
        mock_subscription_cancelled = mocker.patch(
            "squarelet.organizations.models.Organization.subscription_cancelled"
        )

        tasks.process_overdue_invoice(invoice.id)

        # Should cancel subscription
        mock_subscription_cancelled.assert_called_once()

        # Should mark invoice uncollectible in Stripe
        mock_stripe.assert_called_once_with(
            invoice.invoice_id, metadata={"marked_uncollectible": "true"}
        )

        # Should send cancellation email
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_cancelled.html"
        assert call_kwargs["extra_context"]["invoice"] == invoice
        assert call_kwargs["extra_context"]["days_overdue"] == 35

    @pytest.mark.django_db(transaction=True)
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_handles_stripe_error_when_marking_uncollectible(
        self, invoice_factory, organization_factory, subscription_factory, mocker
    ):
        """Should handle Stripe errors gracefully when marking uncollectible"""
        org = organization_factory()
        subscription = subscription_factory(organization=org)
        invoice = invoice_factory(
            organization=org,
            subscription=subscription,
            status="open",
            due_date=date.today() - timedelta(days=35),
        )

        mocker.patch("squarelet.organizations.tasks.send_mail")
        mocker.patch(
            "squarelet.organizations.models.Organization.subscription_cancelled"
        )
        mock_stripe = mocker.patch(
            "stripe.Invoice.modify",
            side_effect=stripe.error.StripeError("API Error"),
        )

        # Should not raise exception
        tasks.process_overdue_invoice(invoice.id)

        # Should still attempt to mark uncollectible
        mock_stripe.assert_called_once_with(
            invoice.invoice_id, metadata={"marked_uncollectible": "true"}
        )

        # Invoice status should remain unchanged due to error
        invoice.refresh_from_db()
        assert invoice.status == "open"

    @pytest.mark.django_db(transaction=True)
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_handles_organization_without_subscription(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should handle organizations without active subscriptions"""
        org = organization_factory()
        invoice = invoice_factory(
            organization=org,
            subscription=None,
            status="open",
            due_date=date.today() - timedelta(days=35),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")
        mock_stripe = mocker.patch("stripe.Invoice.modify")

        # Should not raise exception
        tasks.process_overdue_invoice(invoice.id)

        # Should still mark invoice uncollectible and send email
        mock_stripe.assert_called_once_with(
            mocker.ANY, metadata={"marked_uncollectible": "true"}
        )
        mock_send_mail.assert_called_once()

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=60)
    def test_respects_custom_grace_period(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should respect custom grace period from settings"""
        org = organization_factory()
        # Invoice 50 days overdue (within 60-day grace period)
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=50),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should set payment_failed flag but not cancel
        org.refresh_from_db()
        assert org.payment_failed

        # Should send overdue email, not cancellation email
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_overdue.html"

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_does_not_process_already_paid_invoice(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should skip processing invoices that are not 'open'"""
        org = organization_factory()
        # Create a paid invoice
        invoice = invoice_factory(
            organization=org,
            status="paid",
            due_date=date.today() - timedelta(days=35),
        )

        mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should not process paid invoices - we check the invoice status in
        # the task. (This test verifies the logic works correctly even if
        # called with a paid invoice)
        invoice.refresh_from_db()
        assert invoice.status == "paid"  # Status unchanged

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_sends_intermittent_reminder_emails(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should send reminder emails at intervals during grace period"""
        org = organization_factory(payment_failed=True)
        # Invoice 20 days overdue, last email sent 7 days ago
        # Email interval = 30 // 10 = 3 days, so should send another email
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=20),
            last_overdue_email_sent=date.today() - timedelta(days=7),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should send reminder email
        mock_send_mail.assert_called_once()
        call_kwargs = mock_send_mail.call_args[1]
        assert call_kwargs["template"] == "organizations/email/invoice_overdue.html"

        # Should update last email sent date
        invoice.refresh_from_db()
        assert invoice.last_overdue_email_sent == date.today()

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_does_not_send_email_if_interval_not_reached(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should not send email if interval has not been reached"""
        org = organization_factory(payment_failed=True)
        # Invoice 20 days overdue, last email sent 2 days ago
        # Email interval = 30 // 10 = 3 days, so should NOT send yet
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=20),
            last_overdue_email_sent=date.today() - timedelta(days=2),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should not send email yet
        mock_send_mail.assert_not_called()

        # Should not update last email sent date
        invoice.refresh_from_db()
        assert invoice.last_overdue_email_sent == date.today() - timedelta(days=2)

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=60)
    def test_email_interval_scales_with_grace_period(
        self, invoice_factory, organization_factory, mocker
    ):
        """Email interval should scale with grace period (grace_period // 10)"""
        org = organization_factory(payment_failed=True)
        # Grace period = 60, interval = 6 days
        # Last email sent 5 days ago - should NOT send yet
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=40),
            last_overdue_email_sent=date.today() - timedelta(days=5),
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should not send email yet (5 days < 6 day interval)
        mock_send_mail.assert_not_called()

        # Now test with 6 days passed
        invoice.last_overdue_email_sent = date.today() - timedelta(days=6)
        invoice.save()

        tasks.process_overdue_invoice(invoice.id)

        # Should send email now (6 days >= 6 day interval)
        mock_send_mail.assert_called_once()

    @pytest.mark.django_db
    @override_settings(OVERDUE_INVOICE_GRACE_PERIOD_DAYS=30)
    def test_sends_email_if_last_overdue_email_sent_is_none(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should send email if last_overdue_email_sent is None
        (even with payment_failed=True)"""
        org = organization_factory(payment_failed=True)
        invoice = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=20),
            last_overdue_email_sent=None,
        )

        mock_send_mail = mocker.patch("squarelet.organizations.tasks.send_mail")

        tasks.process_overdue_invoice(invoice.id)

        # Should send email since last_overdue_email_sent is None
        mock_send_mail.assert_called_once()

        # Should set last_overdue_email_sent
        invoice.refresh_from_db()
        assert invoice.last_overdue_email_sent == date.today()


class TestCheckOverdueInvoicesDispatcher:
    """Unit tests for the check_overdue_invoices dispatcher task"""

    @pytest.mark.django_db
    def test_dispatches_tasks_for_overdue_invoices(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should dispatch process_overdue_invoice tasks for all overdue invoices"""
        org = organization_factory()
        # Create 3 overdue invoices
        invoice1 = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=10),
        )
        invoice2 = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=20),
        )
        invoice3 = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=30),
        )

        mock_process = mocker.patch(
            "squarelet.organizations.tasks.process_overdue_invoice.delay"
        )

        tasks.check_overdue_invoices()

        # Should dispatch 3 tasks
        assert mock_process.call_count == 3
        dispatched_ids = {call[0][0] for call in mock_process.call_args_list}
        assert dispatched_ids == {invoice1.id, invoice2.id, invoice3.id}

    @pytest.mark.django_db
    def test_only_dispatches_for_open_invoices(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should only dispatch tasks for invoices with 'open' status"""
        org = organization_factory()
        # Create invoices with various statuses
        invoice_open = invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() - timedelta(days=10),
        )
        invoice_factory(
            organization=org,
            status="paid",
            due_date=date.today() - timedelta(days=10),
        )
        invoice_factory(
            organization=org,
            status="void",
            due_date=date.today() - timedelta(days=10),
        )

        mock_process = mocker.patch(
            "squarelet.organizations.tasks.process_overdue_invoice.delay"
        )

        tasks.check_overdue_invoices()

        # Should only dispatch 1 task for the open invoice
        mock_process.assert_called_once_with(invoice_open.id)

    @pytest.mark.django_db
    def test_does_not_dispatch_for_future_invoices(
        self, invoice_factory, organization_factory, mocker
    ):
        """Should not dispatch tasks for invoices not yet due"""
        org = organization_factory()
        # Create invoice due tomorrow
        invoice_factory(
            organization=org,
            status="open",
            due_date=date.today() + timedelta(days=1),
        )

        mock_process = mocker.patch(
            "squarelet.organizations.tasks.process_overdue_invoice.delay"
        )

        tasks.check_overdue_invoices()

        # Should not dispatch any tasks
        mock_process.assert_not_called()
