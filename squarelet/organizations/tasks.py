# Django
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
from datetime import date, datetime

# Third Party
import stripe

# Squarelet
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.models import Interval
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.models import Charge, Organization, Subscription

logger = logging.getLogger(__name__)
stripe.api_version = "2018-09-24"
stripe.api_key = settings.STRIPE_SECRET_KEY


@shared_task
def restore_organization():
    """Monthly update of organizations subscriptions"""
    subscriptions = Subscription.objects.filter(update_on__lte=date.today())

    # convert to a list so it can be serialized by celery
    uuids = list(subscriptions.values_list("organization__uuid", flat=True))

    # delete cancelled subscriptions first
    subscriptions.filter(cancelled=True).delete()
    subscriptions.update(update_on=date.today() + Interval("1 month"))

    send_cache_invalidations("organization", uuids)


@shared_task(
    name="squarelet.organizations.tasks.handle_charge_succeeded",
    autoretry_for=(Organization.DoesNotExist, stripe.error.RateLimitError),
)
def handle_charge_succeeded(charge_data):
    """Handle receiving a charge.succeeded event from the Stripe webhook"""

    # We autorety if the organization does not exist, as that should mean the webhook
    # is being processed before the database synced the customer id to the organization
    # We can't use transaction.on_commit since we need to return the Charge object
    # when we create it

    if charge_data["customer"] is None:
        # Customer should only be blank for anonymous donations or crowdfunds
        # from MuckRock - no need to log those here
        return

    if charge_data["invoice"]:
        # fetch the invoice from stripe if one associated with the charge
        invoice = stripe.Invoice.retrieve(charge_data["invoice"])
        invoice_line = invoice["lines"]["data"][0]
        if "name" in invoice_line["plan"]:
            plan_name = invoice_line["plan"]["name"]
        else:
            plan_name = stripe.Product.retrieve(invoice_line["plan"]["product"])["name"]
        action = "Subscription Payment"
        description = f"Subscription Payment for {plan_name} plan"
    else:
        plan_name = None
        action = None
        description = charge_data["description"]

    # do not send receipts for MuckRock donations and crowdfunds
    if charge_data["invoice"] and invoice_line["plan"]["id"].lower().startswith(
        ("donate", "crowdfund")
    ):
        return
    if not charge_data["invoice"] and charge_data["metadata"].get(
        "action", ""
    ).lower() in ["donation", "crowdfund-payment"]:
        return

    metadata = charge_data["metadata"]
    if plan_name is not None:
        metadata["plan"] = plan_name
    if action is not None:
        metadata["action"] = action

    charge, _ = Charge.objects.get_or_create(
        charge_id=charge_data["id"],
        defaults={
            "amount": charge_data["amount"],
            "fee_amount": int(charge_data["metadata"].get("fee amount", 0)),
            "organization": lambda: Organization.objects.get(
                customers__customer_id=charge_data["customer"]
            ),
            "created_at": datetime.fromtimestamp(
                charge_data["created"], tz=get_current_timezone()
            ),
            "description": description,
            "metadata": metadata,
        },
    )

    charge.send_receipt()


@shared_task(name="squarelet.organizations.tasks.handle_invoice_failed")
def handle_invoice_failed(invoice_data):
    """Handle receiving a invoice.payment_failed event from the Stripe webhook"""
    try:
        organization = Organization.objects.get(
            customers__customer_id=invoice_data["customer"]
        )
    except Organization.DoesNotExist:
        if invoice_data["lines"]["data"][0]["plan"]["id"] == "donate":
            # donations are handled through muckrock - do not log an error
            return
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
        subject = _("Your subscription has been cancelled")
        organization.subscription_cancelled()
    else:
        subject = _("Your payment has failed")

    send_mail(
        subject=subject,
        template="organizations/email/payment_failed.html",
        organization=organization,
        organization_to=ORG_TO_ADMINS,
        extra_context={"attempt": "final" if attempt == 4 else attempt},
    )


@shared_task(
    name="squarelet.organizations.tasks.backfill_charge_metadata",
    autoretry_for=(stripe.error.RateLimitError,),
)
def backfill_charge_metadata(starting_after=None, keep_running=True):
    """This task for for backfilling in charge metadata.
    It is only meant to be run once upon release, then can be safely removed.
    """
    logger.info("[BCM] Running: starting_after %s", starting_after)
    limit = 25
    # cache product ID/name mapping to reduce API calls
    products = cache.get_or_set(
        "backfill_product_mapping",
        lambda: {p.id: p.name for p in stripe.Product.list().auto_paging_iter()},
    )
    stripe_charges = stripe.Charge.list(limit=limit, starting_after=starting_after)
    last_id = stripe_charges["data"][-1]["id"]
    has_more = stripe_charges["has_more"]

    # we only need to backfill data for recurring charges, which will have an invoice
    stripe_charges = [c for c in stripe_charges["data"] if c["invoice"]]
    charges = Charge.objects.in_bulk(
        [c["id"] for c in stripe_charges], field_name="charge_id"
    )
    logger.info(
        "[BCM] Charges with invoice: %d Charges found: %d",
        len(stripe_charges),
        len(charges),
    )

    for stripe_charge in stripe_charges:
        logger.warning("[BCM] Charge ID: %s", stripe_charge["id"])
        if stripe_charge["id"] not in charges:
            logger.warning("[BCM] Charge ID not found: %s", stripe_charge["id"])
            continue
        charge = charges[stripe_charge["id"]]
        charge.metadata["action"] = "Subscription Payment"

        invoice = stripe.Invoice.retrieve(stripe_charge["invoice"])
        invoice_line = invoice["lines"]["data"][0]
        if "name" in invoice_line["plan"]:
            charge.metadata["plan"] = invoice_line["plan"]["name"]
        else:
            charge.metadata["plan"] = products[invoice_line["plan"]["product"]]

        charge.description = f"Subscription Payment for {charge.metadata['plan']} plan"

    logger.warning("[BCM] bulk updating")
    Charge.objects.bulk_update(charges.values(), ["metadata", "description"])

    logger.warning(
        "[BCM] last_id %s - keep_running %s and has_more %s",
        last_id,
        keep_running,
        has_more,
    )
    if keep_running and has_more:
        backfill_charge_metadata.delay(last_id)
