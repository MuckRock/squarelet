# Django
import sys
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
from datetime import date, datetime
from random import randint

# Third Party
import requests
import stripe

# Squarelet
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.models import Interval
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations import wix
from squarelet.organizations.models.invoice import Invoice
from squarelet.organizations.models.organization import Organization
from squarelet.organizations.models.payment import Charge, Plan, Subscription
from squarelet.users.models import User

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


@shared_task(name="squarelet.organizations.tasks.handle_invoice_created")
def handle_invoice_created(invoice_data):
    """Handle receiving an invoice.created event from the Stripe webhook"""
    try:
        organization = Organization.objects.get(
            customers__customer_id=invoice_data["customer"]
        )
    except Organization.DoesNotExist:
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice created (%s) for customer (%s) with no matching organization",
            invoice_data["id"],
            invoice_data["customer"],
        )
        return

    # Get the subscription if available from the parent object
    subscription = None
    parent = invoice_data.get("parent")
    if parent and parent.get("type") == "subscription_details":
        subscription_id = parent.get("subscription_details", {}).get("subscription")
        if subscription_id:
            try:
                subscription = Subscription.objects.get(subscription_id=subscription_id)
            except Subscription.DoesNotExist:
                logger.warning(
                    "[STRIPE-WEBHOOK-INVOICE] Invoice %s references subscription %s which doesn't exist locally",
                    invoice_data["id"],
                    subscription_id,
                )

    # Create or update the invoice
    Invoice.objects.update_or_create(
        invoice_id=invoice_data["id"],
        defaults={
            "organization": organization,
            "subscription": subscription,
            "amount": invoice_data["amount_due"],
            "due_date": (
                datetime.fromtimestamp(
                    invoice_data["due_date"], tz=get_current_timezone()
                ).date()
                if invoice_data.get("due_date")
                else None
            ),
            "status": invoice_data["status"],
            "created_at": datetime.fromtimestamp(
                invoice_data["created"], tz=get_current_timezone()
            ),
        },
    )
    logger.info("[STRIPE-WEBHOOK-INVOICE] Invoice created/updated: %s", invoice_data["id"])


@shared_task(name="squarelet.organizations.tasks.handle_invoice_finalized")
def handle_invoice_finalized(invoice_data):
    """Handle receiving an invoice.finalized event from the Stripe webhook"""
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_data["id"])
    except Invoice.DoesNotExist:
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice finalized event for non-existent invoice: %s", invoice_data["id"], exc_info=sys.exc_info()
        )
        return

    invoice.status = invoice_data["status"]
    if invoice_data.get("due_date"):
        invoice.due_date = datetime.fromtimestamp(
            invoice_data["due_date"], tz=get_current_timezone()
        ).date()
    invoice.save()
    logger.info("[STRIPE-WEBHOOK-INVOICE] Invoice finalized: %s", invoice_data["id"])


@shared_task(name="squarelet.organizations.tasks.handle_invoice_payment_succeeded")
def handle_invoice_payment_succeeded(invoice_data):
    """Handle receiving an invoice.payment_succeeded event from the Stripe webhook"""
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_data["id"])
    except Invoice.DoesNotExist:
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice payment succeeded event for non-existent invoice: %s",
            invoice_data["id"], exc_info=sys.exc_info()
        )
        return

    invoice.status = "paid"
    invoice.save()

    # Clear payment_failed flag on the organization
    organization = invoice.organization
    if organization.payment_failed:
        organization.payment_failed = False
        organization.save()
        logger.info(
            "[STRIPE-WEBHOOK-INVOICE] Cleared payment_failed flag for organization %s due to invoice payment",
            organization.uuid,
        )

    logger.info("[STRIPE-WEBHOOK-INVOICE] Invoice payment succeeded: %s", invoice_data["id"])


@shared_task(name="squarelet.organizations.tasks.handle_invoice_marked_uncollectible")
def handle_invoice_marked_uncollectible(invoice_data):
    """Handle receiving an invoice.marked_uncollectible event from the Stripe webhook"""
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_data["id"])
    except Invoice.DoesNotExist:
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice marked uncollectible event for non-existent invoice: %s",
            invoice_data["id"], exc_info=sys.exc_info()
        )
        return

    invoice.status = "uncollectible"
    invoice.save()
    logger.info("[STRIPE-WEBHOOK-INVOICE] Invoice marked uncollectible: %s", invoice_data["id"])


@shared_task(name="squarelet.organizations.tasks.handle_invoice_voided")
def handle_invoice_voided(invoice_data):
    """Handle receiving an invoice.voided event from the Stripe webhook"""
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_data["id"])
    except Invoice.DoesNotExist:
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice voided event for non-existent invoice: %s", invoice_data["id"], exc_info=sys.exc_info()
        )
        return

    invoice.status = "void"
    invoice.save()
    logger.info("[STRIPE-WEBHOOK-INVOICE] Invoice voided: %s", invoice_data["id"])


@shared_task(name="squarelet.organizations.tasks.process_overdue_invoice")
def process_overdue_invoice(invoice_id):
    """Process a single overdue invoice"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        logger.error(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Invoice %s not found",
            invoice_id,
        )
        return

    # Skip if invoice is not open
    if invoice.status != "open":
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Skipping invoice %s (status: %s)",
            invoice.invoice_id,
            invoice.status,
        )
        return

    organization = invoice.organization
    grace_period_days = settings.OVERDUE_INVOICE_GRACE_PERIOD_DAYS
    days_overdue = (date.today() - invoice.due_date).days

    logger.info(
        "[STRIPE-PROCESS-OVERDUE-INVOICE] Processing invoice %s for org %s (%d days overdue)",
        invoice.invoice_id,
        organization.uuid,
        days_overdue,
    )

    # If at or past grace period, cancel subscription
    if days_overdue >= grace_period_days:
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Cancelling subscription for org %s due to invoice %s",
            organization.uuid,
            invoice.invoice_id,
        )

        # Cancel subscription (same as credit card failures)
        if organization.subscription:
            organization.subscription_cancelled()
            # Clear subscription reference since it was deleted
            invoice.subscription = None

        # Mark invoice as uncollectible in Stripe
        try:
            stripe.Invoice.modify(
                invoice.invoice_id,
                metadata={"marked_uncollectible": "true"}
            )
            invoice.status = "uncollectible"
            invoice.save()
            logger.info(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Marked invoice %s as uncollectible",
                invoice.invoice_id,
            )
        except stripe.error.StripeError as exc:
            logger.error(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Failed to mark invoice %s as uncollectible: %s",
                invoice.invoice_id,
                exc,
                exc_info=sys.exc_info(),
            )

        # Send cancellation email
        send_mail(
            subject=_("Your subscription has been cancelled due to non-payment"),
            template="organizations/email/invoice_cancelled.html",
            organization=organization,
            organization_to=ORG_TO_ADMINS,
            extra_context={
                "invoice": invoice,
                "days_overdue": days_overdue,
            },
        )
    else:
        # Within grace period - set payment_failed flag and send intermittent warnings
        # Calculate email interval (send ~3 reminders during grace period)
        email_interval_days = max(1, grace_period_days // 10)

        # Check if we should send an email
        should_send_email = False
        if not organization.payment_failed:
            # First time overdue - always send and set flag
            should_send_email = True
            organization.payment_failed = True
            organization.save()
            logger.info(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Set payment_failed flag for org %s",
                organization.uuid,
            )
        elif invoice.last_overdue_email_sent is None:
            # No email sent yet for this invoice - send one
            should_send_email = True
        else:
            # Check if enough time has passed since last email
            days_since_last_email = (date.today() - invoice.last_overdue_email_sent).days
            if days_since_last_email >= email_interval_days:
                should_send_email = True

        if should_send_email:
            # Send overdue invoice email
            send_mail(
                subject=_("Your invoice is overdue"),
                template="organizations/email/invoice_overdue.html",
                organization=organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={
                    "invoice": invoice,
                    "days_overdue": days_overdue,
                    "grace_period_days": grace_period_days,
                    "days_until_cancellation": grace_period_days - days_overdue,
                },
            )

            # Update last email sent date
            invoice.last_overdue_email_sent = date.today()
            invoice.save()

            logger.info(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Sent overdue email for invoice %s (days overdue: %d, interval: %d days)",
                invoice.invoice_id,
                days_overdue,
                email_interval_days,
            )


@shared_task(name="squarelet.organizations.tasks.check_overdue_invoices")
def check_overdue_invoices():
    """Find all overdue invoices and dispatch tasks to process them"""
    # Get all open invoices that are past due (any amount)
    all_overdue_invoices = Invoice.objects.filter(
        status="open",
        due_date__lt=date.today()
    )

    invoice_count = all_overdue_invoices.count()
    logger.info(
        "[STRIPE-CHECK-OVERDUE-INVOICES] Found %d overdue invoices, dispatching tasks",
        invoice_count,
    )

    # Dispatch a task for each overdue invoice
    for invoice in all_overdue_invoices:
        process_overdue_invoice.delay(invoice.id)


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


@shared_task(
    bind=True,
    max_retries=3,
    name="squarelet.organizations.tasks.send_slack_notification",
)
def send_slack_notification(self, slack_webhook, subject, message):
    if isinstance(message, dict):
        # The message is in Slack's block format
        payload = message
        # Fallback text field
        if "text" not in payload:
            payload["text"] = f"{subject}\n\n{message}"
    else:
        # Convert to block format
        payload = {
            "text": f"{subject}\n\n{message}",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{subject}*\n\n{message}"},
                }
            ],
        }

    try:
        response = requests.post(slack_webhook, json=payload, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise self.retry(
            countdown=2**self.request.retries * 30 + randint(0, 30),
            exc=exc,
        )


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def sync_wix(org_id, plan_id, user_id):
    org = Organization.objects.get(pk=org_id)
    plan = Plan.objects.get(pk=plan_id)
    user = User.objects.get(pk=user_id)
    wix.sync_wix(org, plan, user)


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def add_to_waitlist(org_id, plan_id, user_id):
    """Add user to waitlist in Wix"""
    org = Organization.objects.get(pk=org_id)
    plan = Plan.objects.get(pk=plan_id)
    user = User.objects.get(pk=user_id)
    wix.add_to_waitlist(org, plan, user)
