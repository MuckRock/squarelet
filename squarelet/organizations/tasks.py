# Django
from celery.schedules import crontab
from celery.task import periodic_task, task
from django.db.models import Case, F, When
from django.utils.timezone import get_current_timezone

# Standard Library
import logging
from datetime import date, datetime

# Squarelet
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.models import Interval
from squarelet.oidc.middleware import send_cache_invalidations

# Local
from .models import Charge, Organization, Plan

logger = logging.getLogger(__name__)


@periodic_task(run_every=crontab(hour=0, minute=5), name="restore_organizations")
def restore_organization():
    """Monthly update of organizations subscriptions"""
    organizations = Organization.objects.filter(update_on__lte=date.today())
    uuids = organizations.values_list("pk", flat=True)
    organizations.update(
        update_on=Case(
            # if next plan is free, set update_on to NULL
            When(next_plan__base_price=0, next_plan__price_per_user=0, then=None),
            # otherwise, set it to one month from now
            default=date.today() + Interval("1 month"),
        ),
        plan=F("next_plan"),
    )
    send_cache_invalidations("organization", uuids)


@task(name="squarelet.organizations.tasks.handle_charge_succeeded")
def handle_charge_succeeded(charge_data):
    """Handle receiving a charge.succeeded event from the Stripe webhook"""
    try:
        charge = Charge.objects.get(charge_id=charge_data["id"])
    except Charge.DoesNotExist:
        try:
            organization = Organization.objects.get(customer_id=charge_data["customer"])
        except Organization.DoesNotExist:
            logger.error(
                "Charge (%s) made for customer (%s) with no matching organization",
                charge_data["id"],
                charge_data["customer"],
            )
            return

        charge = Charge.objects.create(
            amount=charge_data["amount"],
            organization=organization,
            created_at=datetime.fromtimestamp(
                charge.created, tz=get_current_timezone()
            ),
            charge_id=charge_data["id"],
            description=charge_data["descrption"],
        )
    charge.send_receipt()


@task(name="squarelet.organizations.tasks.handle_invoice_failed")
def handle_invoice_failed(invoice_data):
    """Handle receiving a invoice.payment_failed event from the Stripe webhook"""
    try:
        organization = Organization.objects.get(customer_id=invoice_data["customer"])
    except Organization.DoesNotExist:
        logger.error(
            "Invoice failed (%s) for customer (%s) with no matching organization",
            invoice_data["id"],
            invoice_data["customer"],
        )
        return

    organization.payment_failed = True
    organization.save()

    logger.info("Payment failed: %s", invoice_data)

    attempt = invoice_data["attempt_count"]
    if attempt == 4:
        subject = "Your subscription has been cancelled"
        organization.set_subscription(
            token=None,
            plan=Plan.objects.get(slug="free"),
            max_users=organization.max_users,
        )
    else:
        subject = "Your payment has failed"

    send_mail(
        subject=subject,
        template="organizations/email/payment_failed.html",
        organization=organization,
        organization_to=ORG_TO_ADMINS,
        extra_context={"attempt": "final" if attempt == 4 else attempt},
    )
