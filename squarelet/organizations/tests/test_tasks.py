# Django
from django.utils import timezone

# Standard Library
from datetime import date, timedelta

# Third Party
import pytest
from dateutil.relativedelta import relativedelta

# Squarelet
from squarelet.organizations import tasks
from squarelet.organizations.models import Charge, Invoice, Subscription
from squarelet.organizations.tests.factories import (
    InvoiceFactory,
    SubscriptionFactory,
)


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
        invoice = invoice_factory(
            invoice_id="in_123", organization=organization, status="open"
        )

        invoice_data = {"id": "in_123"}

        tasks.handle_invoice_payment_succeeded(invoice_data)

        organization.refresh_from_db()
        assert organization.payment_failed is False

    @pytest.mark.django_db
    def test_does_not_change_flag_if_already_false(
        self, organization_factory, invoice_factory
    ):
        organization = organization_factory(payment_failed=False)
        invoice = invoice_factory(
            invoice_id="in_123", organization=organization, status="open"
        )

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
