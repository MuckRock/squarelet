# Django
from django.core.management.base import BaseCommand
from django.utils.timezone import get_current_timezone

# Standard Library
import logging
from datetime import datetime

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.invoice import Invoice
from squarelet.organizations.models.payment import (
    Customer,
    Subscription,
    get_payment_brand,
)
from squarelet.organizations.payments.factory import get_payment_provider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Backfill locally-cached Stripe fields for existing records.

    Populates:
      - Customer: payment_brand, payment_last4, payment_exp_month,
                  payment_exp_year, stripe_payment_method_id
      - Subscription: stripe_status, current_period_end
      - Invoice: hosted_invoice_url

    Safe to re-run: skips records that already have their cache populated.
    Use --force to overwrite existing cached values.
    """

    help = "Backfill cached Stripe fields on Customer, Subscription, and Invoice"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch and overwrite already-cached values",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be updated without writing to the database",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        provider = get_payment_provider()

        if dry_run:
            self.stdout.write("DRY RUN — no changes will be written.\n")

        self._backfill_customers(provider, force, dry_run)
        self._backfill_subscriptions(provider, force, dry_run)
        self._backfill_invoices(provider, force, dry_run)

    def _backfill_customers(self, provider, force, dry_run):
        # pylint: disable=too-many-locals
        customer_service = provider.get_customer_service()

        qs = Customer.objects.exclude(customer_id=None)
        if not force:
            qs = qs.filter(payment_brand="", stripe_payment_method_id="")

        total = qs.count()
        self.stdout.write(f"Backfilling {total} Customer record(s)...\n")
        updated = skipped = errors = 0

        for customer in qs.iterator():
            try:
                stripe_customer = customer_service.retrieve(customer.customer_id)
                invoice_settings = getattr(stripe_customer, "invoice_settings", None)
                pm_id = invoice_settings and invoice_settings.default_payment_method
                if pm_id and isinstance(pm_id, str) and pm_id.startswith("pm_"):
                    pm = customer_service.retrieve_payment_method(pm_id)
                    details = getattr(pm, pm.type, None)
                    customer.payment_brand = (
                        get_payment_brand(details) if details else ""
                    )
                    customer.payment_last4 = getattr(details, "last4", "") or ""
                    customer.payment_exp_month = getattr(details, "exp_month", None)
                    customer.payment_exp_year = getattr(details, "exp_year", None)
                    customer.stripe_payment_method_id = pm_id
                elif stripe_customer.default_source:
                    source = customer_service.retrieve_source(
                        stripe_customer,
                        stripe_customer.default_source,
                    )
                    customer.payment_brand = get_payment_brand(source)
                    customer.payment_last4 = getattr(source, "last4", "") or ""
                    customer.payment_exp_month = getattr(source, "exp_month", None)
                    customer.payment_exp_year = getattr(source, "exp_year", None)
                    customer.stripe_payment_method_id = source.id
                else:
                    skipped += 1
                    continue

                if not dry_run:
                    customer.save_payment_cache()
                updated += 1
            except stripe.StripeError as exc:
                logger.warning(
                    "[BACKFILL] Error fetching customer %s: %s",
                    customer.customer_id,
                    exc,
                )
                errors += 1

        self.stdout.write(
            f"  Customers: {updated} updated, {skipped} skipped "
            f"(no default PM), {errors} errors\n"
        )

    def _backfill_subscriptions(self, provider, force, dry_run):
        sub_service = provider.get_subscription_service()

        qs = Subscription.objects.exclude(subscription_id=None)
        if not force:
            qs = qs.filter(stripe_status="")

        total = qs.count()
        self.stdout.write(f"Backfilling {total} Subscription record(s)...\n")
        updated = errors = 0

        for subscription in qs.iterator():
            try:
                stripe_sub = sub_service.retrieve(subscription.subscription_id)
                subscription.stripe_status = stripe_sub.status or ""
                ts = sub_service.get_current_period_end(stripe_sub)
                subscription.current_period_end = (
                    datetime.fromtimestamp(ts, tz=get_current_timezone())
                    if ts
                    else None
                )
                if not dry_run:
                    subscription.save(
                        update_fields=["stripe_status", "current_period_end"]
                    )
                updated += 1
            except stripe.StripeError as exc:
                logger.warning(
                    "[BACKFILL] Error fetching subscription %s: %s",
                    subscription.subscription_id,
                    exc,
                )
                errors += 1

        self.stdout.write(f"  Subscriptions: {updated} updated, {errors} errors\n")

    def _backfill_invoices(self, provider, force, dry_run):
        invoice_service = provider.get_invoice_service()

        qs = Invoice.objects.all()
        if not force:
            qs = qs.filter(hosted_invoice_url="")

        total = qs.count()
        self.stdout.write(f"Backfilling {total} Invoice record(s)...\n")
        updated = skipped = errors = 0

        for invoice in qs.iterator():
            try:
                stripe_invoice = invoice_service.retrieve(invoice.invoice_id)
                url = stripe_invoice.get("hosted_invoice_url", "") or ""
                if not url:
                    skipped += 1
                    continue
                invoice.hosted_invoice_url = url
                if not dry_run:
                    invoice.save(update_fields=["hosted_invoice_url"])
                updated += 1
            except stripe.StripeError as exc:
                logger.warning(
                    "[BACKFILL] Error fetching invoice %s: %s",
                    invoice.invoice_id,
                    exc,
                )
                errors += 1

        self.stdout.write(
            f"  Invoices: {updated} updated, {skipped} skipped "
            f"(no URL), {errors} errors\n"
        )
