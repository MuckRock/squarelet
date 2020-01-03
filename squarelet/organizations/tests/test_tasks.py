# Django
from django.utils import timezone

# Standard Library
from datetime import date, timedelta

# Third Party
import pytest
from dateutil.relativedelta import relativedelta

# Local
from .. import tasks
from ..models import Charge


@pytest.mark.django_db()
def _test_restore_organization(
    organization_factory, free_plan_factory, organization_plan_factory, mocker
):
    # XXX
    patched = mocker.patch("squarelet.organizations.tasks.send_cache_invalidations")
    mocker.patch("stripe.Plan.create")
    today = date.today()
    free_plan = free_plan_factory()
    organization_plan = organization_plan_factory()
    org_update_later = organization_factory(
        update_on=today + timedelta(1), plan=organization_plan, next_plan=free_plan
    )
    org_update_free = organization_factory(
        update_on=today - timedelta(1), plan=organization_plan, next_plan=free_plan
    )
    org_update = organization_factory(
        update_on=today - timedelta(1),
        plan=organization_plan,
        next_plan=organization_plan,
    )
    tasks.restore_organization()

    org_update_later.refresh_from_db()
    org_update_free.refresh_from_db()
    org_update.refresh_from_db()

    # update later should have not been changed
    assert org_update_later.update_on == today + timedelta(1)
    assert org_update_later.plan == organization_plan

    assert org_update_free.plan == free_plan
    assert org_update_free.update_on is None

    assert org_update.plan == organization_plan
    assert org_update.update_on == today + relativedelta(months=1)

    patched.assert_called_with("organization", [org_update_free.uuid, org_update.uuid])


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
        organization = organization_factory(customer_id=charge_data["customer"])
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
        assert charge.description == product["name"]
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
        organization = organization_factory(customer_id=charge_data["customer"])
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

        tasks.handle_charge_succeeded(charge_data)


@pytest.mark.django_db()
def test_handle_invoice_failed(organization_factory, user_factory, mailoutbox):
    user = user_factory()
    organization = organization_factory(admins=[user], customer_id="cus_123")
    invoice_data = {"id": 1, "customer": organization.customer_id, "attempt_count": 2}
    tasks.handle_invoice_failed(invoice_data)
    organization.refresh_from_db()
    assert organization.payment_failed
    mail = mailoutbox[0]
    assert mail.subject == "Your payment has failed"
    assert mail.to == [user.email]
