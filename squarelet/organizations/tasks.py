# Django
from celery import shared_task
from django.conf import settings
from django.db.models import F, Q
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys
from datetime import date, datetime
from random import randint

# Third Party
import requests
import stripe

# Squarelet
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.models import Interval
from squarelet.core.utils import get_stripe_dashboard_url, is_production_env
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations import wix
from squarelet.organizations.models.invoice import Invoice
from squarelet.organizations.models.organization import Organization
from squarelet.organizations.models.payment import (
    Charge,
    EntitlementGrant,
    Plan,
    Subscription,
)
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.users.models import User

logger = logging.getLogger(__name__)


@shared_task
def restore_organization():
    """Monthly refresh of subscriptions and entitlement grants"""
    today = date.today()

    # --- Subscriptions ---
    due_org_ids = list(
        Organization.objects.filter(update_on__lte=today).values_list("id", flat=True)
    )
    due_org_uuids = list(
        Organization.objects.filter(id__in=due_org_ids).values_list("uuid", flat=True)
    )

    # Delete cancelled subscriptions for due orgs where the Stripe cancellation
    # date has passed (or is null, which covers free plans and legacy records).
    Subscription.objects.filter(
        organization_id__in=due_org_ids,
        cancelled=True,
    ).filter(Q(cancel_at__lte=today) | Q(cancel_at__isnull=True)).delete()

    # Determine which orgs still have active subscriptions
    orgs_with_subs = set(
        Subscription.objects.filter(organization_id__in=due_org_ids).values_list(
            "organization_id", flat=True
        )
    )
    orgs_without_subs = set(due_org_ids) - orgs_with_subs

    # Advance anchor date for orgs that still have subscriptions
    Organization.objects.filter(id__in=orgs_with_subs).update(
        update_on=F("update_on") + Interval("1 month")
    )
    # Clear anchor for orgs whose last subscription was just cancelled
    Organization.objects.filter(id__in=orgs_without_subs).update(update_on=None)

    # --- Grant-only orgs ---
    # Orgs that have entitlement grants but no subscription have no stored
    # update_on.  Their resources refresh on the 1st of each month.
    grant_uuids = set()
    if today.day == 1:
        active_grants = list(EntitlementGrant.objects.filter(active=True))
        if active_grants:
            qs_list = [
                g.matching_organizations().filter(update_on__isnull=True).values("uuid")
                for g in active_grants
            ]
            union_qs = qs_list[0].union(*qs_list[1:])
            grant_uuids = {row["uuid"] for row in union_qs}

    all_uuids = list({*due_org_uuids, *grant_uuids})
    send_cache_invalidations("organization", all_uuids)


@shared_task(
    name="squarelet.organizations.tasks.handle_charge_succeeded",
    autoretry_for=(Organization.DoesNotExist, stripe.RateLimitError),
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
        provider = get_payment_provider()
        invoice = provider.get_invoice_service().retrieve(charge_data["invoice"])
        try:
            invoice_line = invoice["lines"]["data"][0]
            # invoice_line["plan"] was removed in Stripe API 2025-03-31.basil;
            # plan/price info is now at invoice_line["pricing"]["price_details"]
            price_details = invoice_line["pricing"]["price_details"]
            plan_name = provider.get_plan_service().retrieve_product(
                price_details["product"]
            )["name"]
            action = "Subscription Payment"
            description = f"Subscription Payment for {plan_name} plan"
        except (TypeError, IndexError, KeyError):
            # The invoice data doesn't exist
            invoice_line = None
            plan_name = None
            action = None
            description = charge_data["description"]
    else:
        invoice_line = None
        plan_name = None
        action = None
        description = charge_data["description"]

    # do not send receipts for MuckRock donations and crowdfunds
    if (
        charge_data["invoice"]
        and invoice_line
        and invoice_line["pricing"]["price_details"]["price"]
        .lower()
        .startswith(("donate", "crowdfund"))
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
        # Look up the specific subscription from the invoice data
        subscription = None
        parent = invoice_data.get("parent")
        if parent and parent.get("type") == "subscription_details":
            stripe_sub_id = parent.get("subscription_details", {}).get("subscription")
            if stripe_sub_id:
                try:
                    subscription = Subscription.objects.get(
                        subscription_id=stripe_sub_id
                    )
                except Subscription.DoesNotExist:
                    logger.error(
                        "Invoice failed (%s): no local subscription found for "
                        "Stripe subscription %s on organization %s — "
                        "manual intervention required",
                        invoice_data["id"],
                        stripe_sub_id,
                        organization.uuid,
                    )
                    return
        if subscription is None:
            logger.error(
                "Invoice failed (%s): could not determine subscription for "
                "organization %s — manual intervention required",
                invoice_data["id"],
                organization.uuid,
            )
            return
        organization.subscription_cancelled(subscription=subscription)
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
        invoice_id = invoice_data["id"]
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice created for customer with no matching "
            "organization: %s (%s)",
            invoice_id,
            stripe_link,
        )
        return

    # Get the subscription from the parent object — only track subscription invoices
    subscription = None
    parent = invoice_data.get("parent")
    if parent and parent.get("type") == "subscription_details":
        subscription_id = parent.get("subscription_details", {}).get("subscription")
        if subscription_id:
            try:
                subscription = Subscription.objects.get(subscription_id=subscription_id)
            except Subscription.DoesNotExist:
                invoice_id = invoice_data["id"]
                stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
                logger.warning(
                    "[STRIPE-WEBHOOK-INVOICE] Invoice references missing subscription, "
                    "skipping: %s (%s)",
                    invoice_id,
                    stripe_link,
                )
                return

    if subscription is None:
        invoice_id = invoice_data["id"]
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.info(
            "[STRIPE-WEBHOOK-INVOICE] Skipping invoice with no subscription: %s (%s)",
            invoice_id,
            stripe_link,
        )
        return

    # Create or update the invoice
    # Note: Invoice may already exist if created synchronously during subscription start
    _invoice, created = Invoice.create_or_update_from_stripe(
        invoice_data, organization, subscription
    )
    invoice_id = invoice_data["id"]
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    action = "created" if created else "updated"
    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice %s via webhook: %s (%s)",
        action,
        invoice_id,
        stripe_link,
    )


@shared_task(name="squarelet.organizations.tasks.handle_invoice_updated")
def handle_invoice_updated(invoice_data):
    """Handle receiving an invoice.updated event from the Stripe webhook"""
    invoice_id = invoice_data["id"]
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.info(
            "[STRIPE-WEBHOOK-INVOICE] Received update event for invoice not tracked "
            "in our system: %s (%s)",
            invoice_id,
            stripe_link,
        )
        return

    Invoice.create_or_update_from_stripe(
        invoice_data, invoice.organization, invoice.subscription
    )
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice updated: %s (%s)", invoice_id, stripe_link
    )


@shared_task(name="squarelet.organizations.tasks.handle_invoice_finalized")
def handle_invoice_finalized(invoice_data):
    """Handle receiving an invoice.finalized event from the Stripe webhook"""
    invoice_id = invoice_data["id"]
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice finalized event for non-existent "
            "invoice: %s (%s)",
            invoice_id,
            stripe_link,
            exc_info=sys.exc_info(),
        )
        return

    Invoice.create_or_update_from_stripe(
        invoice_data, invoice.organization, invoice.subscription
    )
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice finalized: %s (%s)", invoice_id, stripe_link
    )


@shared_task(name="squarelet.organizations.tasks.handle_invoice_paid")
def handle_invoice_paid(invoice_data):
    """Handle receiving an invoice.paid event from the Stripe webhook"""
    invoice_id = invoice_data["id"]
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice payment succeeded event for "
            "non-existent invoice: %s (%s)",
            invoice_id,
            stripe_link,
            exc_info=sys.exc_info(),
        )
        return

    Invoice.create_or_update_from_stripe(
        invoice_data, invoice.organization, invoice.subscription
    )

    # Clear payment_failed flag on the organization
    organization = invoice.organization
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    if organization.payment_failed:
        organization.payment_failed = False
        organization.save()
        logger.info(
            "[STRIPE-WEBHOOK-INVOICE] Cleared "
            "payment_failed flag for org %s (invoice paid): "
            "%s (%s)",
            organization.uuid,
            invoice_id,
            stripe_link,
        )

    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice payment succeeded: %s (%s)",
        invoice_id,
        stripe_link,
    )


@shared_task(name="squarelet.organizations.tasks.handle_invoice_marked_uncollectible")
def handle_invoice_marked_uncollectible(invoice_data):
    """Handle receiving an invoice.marked_uncollectible event from the Stripe webhook"""
    invoice_id = invoice_data["id"]
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice marked uncollectible event for "
            "non-existent invoice: %s (%s)",
            invoice_id,
            stripe_link,
            exc_info=sys.exc_info(),
        )
        return

    invoice.status = "uncollectible"
    invoice.save()
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice marked uncollectible: %s (%s)",
        invoice_id,
        stripe_link,
    )


@shared_task(name="squarelet.organizations.tasks.handle_invoice_voided")
def handle_invoice_voided(invoice_data):
    """Handle receiving an invoice.voided event from the Stripe webhook"""
    invoice_id = invoice_data["id"]
    try:
        invoice = Invoice.objects.get(invoice_id=invoice_id)
    except Invoice.DoesNotExist:
        stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
        logger.error(
            "[STRIPE-WEBHOOK-INVOICE] Invoice voided event for non-existent "
            "invoice: %s (%s)",
            invoice_id,
            stripe_link,
            exc_info=sys.exc_info(),
        )
        return

    invoice.status = "void"
    invoice.save()
    stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
    logger.info(
        "[STRIPE-WEBHOOK-INVOICE] Invoice voided: %s (%s)", invoice_id, stripe_link
    )


def _cancel_subscription_for_invoice(invoice, organization):
    """Cancel the subscription associated with an overdue invoice."""
    if invoice.subscription:
        organization.subscription_cancelled(invoice.subscription)
        invoice.subscription = None


def _should_send_overdue_email(organization, invoice, email_interval_days):
    """Return True if an overdue warning email should be sent now."""
    if not organization.payment_failed:
        organization.payment_failed = True
        organization.save()
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Set payment_failed flag for org %s",
            organization.uuid,
        )
        return True
    if invoice.last_overdue_email_sent is None:
        return True
    days_since_last_email = (date.today() - invoice.last_overdue_email_sent).days
    return days_since_last_email >= email_interval_days


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

    if invoice.status != "open":
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Skipping invoice %s (status: %s)",
            invoice.invoice_id,
            invoice.status,
        )
        return

    if invoice.amount == 0:
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Skipping $0 invoice %s",
            invoice.invoice_id,
        )
        return

    organization = invoice.organization
    grace_period_days = settings.OVERDUE_INVOICE_GRACE_PERIOD_DAYS
    days_overdue = (date.today() - invoice.due_date).days

    logger.info(
        "[STRIPE-PROCESS-OVERDUE-INVOICE] Processing invoice %s for org "
        "%s (%d days overdue)",
        invoice.invoice_id,
        organization.uuid,
        days_overdue,
    )

    if days_overdue >= grace_period_days:
        logger.info(
            "[STRIPE-PROCESS-OVERDUE-INVOICE] Cancelling subscription for "
            "org %s due to invoice %s",
            organization.uuid,
            invoice.invoice_id,
        )
        _cancel_subscription_for_invoice(invoice, organization)
        try:
            invoice.mark_uncollectible_in_stripe()
            invoice.status = "uncollectible"
            invoice.save()
            logger.info(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Marked invoice %s as uncollectible",
                invoice.invoice_id,
            )
        except stripe.StripeError as exc:
            logger.error(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Failed to mark invoice %s "
                "as uncollectible: %s",
                invoice.invoice_id,
                exc,
                exc_info=sys.exc_info(),
            )
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
        email_interval_days = max(1, grace_period_days // 10)
        if _should_send_overdue_email(organization, invoice, email_interval_days):
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
                    "hosted_invoice_url": invoice.get_hosted_invoice_url(),
                },
            )
            invoice.last_overdue_email_sent = date.today()
            invoice.save()
            logger.info(
                "[STRIPE-PROCESS-OVERDUE-INVOICE] Sent overdue email for "
                "invoice %s (days overdue: %d, interval: %d days)",
                invoice.invoice_id,
                days_overdue,
                email_interval_days,
            )


@shared_task(name="squarelet.organizations.tasks.check_overdue_invoices")
def check_overdue_invoices():
    """Find all overdue invoices and dispatch tasks to process them"""
    # Get all open invoices that are past due with a non-zero amount
    all_overdue_invoices = Invoice.objects.filter(
        status="open", due_date__lt=date.today(), amount__gt=0
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
    # Only sync to Wix in production
    if not is_production_env():
        logger.info(
            "[WIX-SYNC] Skipping Wix sync in non-production environment (ENV=%s)",
            settings.ENV,
        )
        return

    org = Organization.objects.get(pk=org_id)
    plan = Plan.objects.get(pk=plan_id)
    user = User.objects.get(pk=user_id)
    wix.sync_wix(org, plan, user)


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def sync_wix_for_group_member(member_org_id, group_org_id, plan_id):
    """Sync all users of a member organization to Wix using the group's plan.

    This is used when:
    - An organization joins a group that has a Wix plan with share_resources=True
    - A group subscribes to a Wix plan and needs to sync all member org users
    - share_resources is toggled on for a group with a Wix plan
    """
    if not is_production_env():
        logger.info(
            "[WIX-SYNC] Skipping group member Wix sync "
            "in non-production environment (ENV=%s)",
            settings.ENV,
        )
        return

    member_org = Organization.objects.get(pk=member_org_id)
    group_org = Organization.objects.get(pk=group_org_id)
    plan = Plan.objects.get(pk=plan_id)

    # Verify conditions still apply
    if not group_org.share_resources:
        logger.info(
            "[WIX-SYNC] Group %s no longer shares resources, skipping sync",
            group_org_id,
        )
        return

    if not plan.wix:
        logger.info(
            "[WIX-SYNC] Plan %s no longer has wix enabled, skipping sync",
            plan_id,
        )
        return

    logger.info(
        "[WIX-SYNC] Syncing %d users from member org %s to group %s's Wix plan %s",
        member_org.users.count(),
        member_org_id,
        group_org_id,
        plan_id,
    )

    for user in member_org.users.all():
        wix.sync_wix(member_org, plan, user)


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def unsync_wix(org_id, plan_id, user_id):
    """Remove Wix labels for a user when they leave an organization or plan changes."""
    if not is_production_env():
        logger.info(
            "[WIX-SYNC] Skipping Wix unsync in non-production environment (ENV=%s)",
            settings.ENV,
        )
        return

    org = Organization.objects.get(pk=org_id)
    plan = Plan.objects.get(pk=plan_id)
    user = User.objects.get(pk=user_id)
    wix.unsync_wix(org, plan, user)


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def unsync_wix_for_group_member(member_org_id, group_org_id, plan_id):
    """Remove Wix labels for all users of a member organization.

    This is used when:
    - An organization leaves a group that has a Wix plan
    - A group's Wix plan subscription is cancelled
    - share_resources is toggled off for a group with a Wix plan
    """
    if not is_production_env():
        logger.info(
            "[WIX-SYNC] Skipping group member Wix unsync "
            "in non-production environment (ENV=%s)",
            settings.ENV,
        )
        return

    member_org = Organization.objects.get(pk=member_org_id)
    group_org = Organization.objects.get(pk=group_org_id)
    plan = Plan.objects.get(pk=plan_id)

    if not group_org.share_resources:
        logger.info(
            "[WIX-SYNC] Group %s no longer shares resources, skipping unsync",
            group_org_id,
        )
        return

    if not plan.wix:
        logger.info(
            "[WIX-SYNC] Plan %s no longer has wix enabled, skipping unsync",
            plan_id,
        )
        return

    logger.info(
        "[WIX-SYNC] Unsyncing %d users from member org %s "
        "from group %s's Wix plan %s",
        member_org.users.count(),
        member_org_id,
        group_org_id,
        plan_id,
    )

    for user in member_org.users.all():
        wix.unsync_wix(member_org, plan, user)


@shared_task(
    autoretry_for=(requests.exceptions.RequestException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def add_to_waitlist(org_id, plan_id, user_id):
    """Add user to waitlist in Wix"""
    # Only add to waitlist in production
    if not is_production_env():
        logger.info(
            "[WIX-WAITLIST] Skipping Wix waitlist"
            " in non-production environment (ENV=%s)",
            settings.ENV,
        )
        return

    org = Organization.objects.get(pk=org_id)
    plan = Plan.objects.get(pk=plan_id)
    user = User.objects.get(pk=user_id)
    wix.add_to_waitlist(org, plan, user)
