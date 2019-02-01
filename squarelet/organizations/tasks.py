# Django
from celery.schedules import crontab
from celery.task import periodic_task, task
from django.db.models import F
from django.utils.timezone import get_current_timezone

# Standard Library
from datetime import date, datetime

# Squarelet
from squarelet.core.models import Interval
from squarelet.oidc.middleware import send_cache_invalidations

# Local
from .models import Charge, Organization, Plan


@periodic_task(run_every=crontab(hour=0, minute=5), name="restore_organizations")
def restore_organization():
    """Monthly update of organizations subscriptions"""
    organizations = Organization.objects.filter(update_on__lte=date.today())
    uuids = organizations.values_list("pk", flat=True)
    organizations.update(
        update_on=date.today() + Interval("1 month"), plan=F("next_plan")
    )
    # XXX send single cache invalidation for all uuids
    for uuid in uuids:
        send_cache_invalidations("organization", uuid)


@task(name="squarelet.organizations.tasks.handle_charge_succeeded")
def handle_charge_succeeded(charge_data):
    """Handle receiving a charge.succeeded event from the Stripe webhook"""
    try:
        charge = Charge.objects.get(charge_id=charge_data["id"])
    except Charge.DoesNotExist:
        # XXX error handle missing organization
        organization = Organization.objects.get(customer_id=charge_data["customer"])
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
    attempt = invoice_data["attempt_count"]
    organization = Organization.objects.get(customer_id=invoice_data["customer"])
    # XXX handle recurring donations and crowdfunds here
    organization.payment_failed = True
    organization.save()

    # XXX send email notification

    # XXX log

    # XXX only if for a regular payment plan
    if attempt == 4:
        # XXX cancel subscription, send email
        organization.set_subscription(
            None, Plan.objects.get(slug="free"), organization.max_users
        )
