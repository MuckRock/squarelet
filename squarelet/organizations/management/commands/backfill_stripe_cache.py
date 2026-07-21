# Django
from django.core.management.base import BaseCommand
from django.utils.timezone import get_current_timezone

# Standard Library
import logging
import time
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

logger = logging.getLogger(__name__)

BATCH_SIZE = 500

# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=broad-exception-caught


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
            help=("Report what would be updated without writing" " to the database"),
        )
        parser.add_argument(
            "--customers-only",
            action="store_true",
            help="Only backfill Customer records",
        )
        parser.add_argument(
            "--subscriptions-only",
            action="store_true",
            help="Only backfill Subscription records",
        )
        parser.add_argument(
            "--invoices-only",
            action="store_true",
            help="Only backfill Invoice records",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        # If no --*-only flag is set, run all three
        run_all = not any(
            options[k]
            for k in ("customers_only", "subscriptions_only", "invoices_only")
        )

        if dry_run:
            self.stdout.write("DRY RUN — no changes will be written.\n")

        if run_all or options["customers_only"]:
            self._backfill_customers(force, dry_run)
        if run_all or options["subscriptions_only"]:
            self._backfill_subscriptions(force, dry_run)
        if run_all or options["invoices_only"]:
            self._backfill_invoices(force, dry_run)

    # -- customers ---------------------------------------------------

    def _backfill_customers(self, force, dry_run):
        qs = Customer.objects.exclude(customer_id=None)
        if not force:
            qs = qs.filter(payment_brand="", stripe_payment_method_id="")

        # Build a lookup: stripe customer_id -> local Customer
        local_map = {}
        for customer in qs.iterator():
            local_map[customer.customer_id] = customer

        total = len(local_map)
        self.stdout.write(
            f"Backfilling {total} Customer record(s) " f"via Stripe list API...\n"
        )
        if total == 0:
            return

        updated = skipped = errors = 0
        fetched = 0
        batch = []
        start = time.monotonic()

        # Page through all Stripe customers, expanding payment info
        for stripe_cust in stripe.Customer.list(
            limit=100,
            expand=[
                "data.default_source",
                "data.invoice_settings.default_payment_method",
            ],
        ).auto_paging_iter():
            fetched += 1
            if fetched % 1000 == 0:
                elapsed = time.monotonic() - start
                self.stdout.write(
                    f"  [customers] Scanned {fetched} Stripe"
                    f" records, {updated} matched & updated"
                    f" ({elapsed:.0f}s elapsed)\n"
                )

            customer = local_map.get(stripe_cust.id)
            if customer is None:
                continue

            try:
                invoice_settings = getattr(stripe_cust, "invoice_settings", None)
                pm = invoice_settings and invoice_settings.default_payment_method

                if pm and not isinstance(pm, str):
                    # Expanded PaymentMethod object
                    details = getattr(pm, pm.type, None)
                    customer.payment_brand = (
                        get_payment_brand(details) if details else ""
                    )
                    customer.payment_last4 = getattr(details, "last4", "") or ""
                    customer.payment_exp_month = getattr(details, "exp_month", None)
                    customer.payment_exp_year = getattr(details, "exp_year", None)
                    customer.stripe_payment_method_id = pm.id
                elif stripe_cust.default_source and not isinstance(
                    stripe_cust.default_source, str
                ):
                    # Expanded source object
                    source = stripe_cust.default_source
                    customer.payment_brand = get_payment_brand(source)
                    customer.payment_last4 = getattr(source, "last4", "") or ""
                    customer.payment_exp_month = getattr(source, "exp_month", None)
                    customer.payment_exp_year = getattr(source, "exp_year", None)
                    customer.stripe_payment_method_id = source.id
                else:
                    skipped += 1
                    continue

                batch.append(customer)
                updated += 1

                if len(batch) >= BATCH_SIZE:
                    if not dry_run:
                        Customer.objects.bulk_update(
                            batch,
                            Customer.PAYMENT_CACHE_FIELDS,
                            batch_size=BATCH_SIZE,
                        )
                    batch = []
            except stripe.StripeError as exc:
                logger.warning(
                    "[BACKFILL] Error processing customer %s: %s",
                    stripe_cust.id,
                    exc,
                )
                errors += 1

        # Flush remaining batch
        if batch and not dry_run:
            Customer.objects.bulk_update(
                batch,
                Customer.PAYMENT_CACHE_FIELDS,
                batch_size=BATCH_SIZE,
            )

        elapsed = time.monotonic() - start
        self.stdout.write(
            f"  Customers done: {updated} updated, {skipped} skipped"
            f" (no default PM), {errors} errors."
            f" Scanned {fetched} Stripe records in {elapsed:.0f}s.\n"
        )

    # -- subscriptions -----------------------------------------------

    def _backfill_subscriptions(self, force, dry_run):
        qs = Subscription.objects.exclude(subscription_id=None)
        if not force:
            qs = qs.filter(stripe_status="")

        local_map = {}
        for sub in qs.iterator():
            local_map[sub.subscription_id] = sub

        total = len(local_map)
        self.stdout.write(
            f"Backfilling {total} Subscription record(s) " f"via Stripe list API...\n"
        )
        if total == 0:
            return

        updated = errors = 0
        fetched = 0
        batch = []
        start = time.monotonic()
        tz = get_current_timezone()

        # Include canceled subs so we can backfill their final status
        for stripe_sub in stripe.Subscription.list(
            limit=100,
            status="all",
        ).auto_paging_iter():
            fetched += 1
            if fetched % 1000 == 0:
                elapsed = time.monotonic() - start
                self.stdout.write(
                    f"  [subscriptions] Scanned {fetched} Stripe"
                    f" records, {updated} matched & updated"
                    f" ({elapsed:.0f}s elapsed)\n"
                )

            sub = local_map.get(stripe_sub.id)
            if sub is None:
                continue

            try:
                sub.stripe_status = stripe_sub.status or ""
                # current_period_end moved to items in newer API
                items = stripe_sub.items
                ts = items.data[0].current_period_end if items and items.data else None
                sub.current_period_end = (
                    datetime.fromtimestamp(ts, tz=tz) if ts else None
                )
                batch.append(sub)
                updated += 1

                if len(batch) >= BATCH_SIZE:
                    if not dry_run:
                        Subscription.objects.bulk_update(
                            batch,
                            ["stripe_status", "current_period_end"],
                            batch_size=BATCH_SIZE,
                        )
                    batch = []
            except (stripe.StripeError, Exception) as exc:
                logger.warning(
                    "[BACKFILL] Error processing subscription %s: %s",
                    stripe_sub.id,
                    exc,
                )
                errors += 1

        # Flush remaining batch
        if batch and not dry_run:
            Subscription.objects.bulk_update(
                batch,
                ["stripe_status", "current_period_end"],
                batch_size=BATCH_SIZE,
            )

        elapsed = time.monotonic() - start
        self.stdout.write(
            f"  Subscriptions done: {updated} updated, {errors} errors."
            f" Scanned {fetched} Stripe records in {elapsed:.0f}s.\n"
        )

    # -- invoices ----------------------------------------------------

    def _backfill_invoices(self, force, dry_run):
        qs = Invoice.objects.all()
        if not force:
            qs = qs.filter(hosted_invoice_url="")

        local_map = {}
        for inv in qs.iterator():
            local_map[inv.invoice_id] = inv

        total = len(local_map)
        self.stdout.write(
            f"Backfilling {total} Invoice record(s) " f"via Stripe list API...\n"
        )
        if total == 0:
            return

        updated = skipped = errors = 0
        fetched = 0
        batch = []
        start = time.monotonic()

        for stripe_inv in stripe.Invoice.list(
            limit=100,
        ).auto_paging_iter():
            fetched += 1
            if fetched % 1000 == 0:
                elapsed = time.monotonic() - start
                self.stdout.write(
                    f"  [invoices] Scanned {fetched} Stripe"
                    f" records, {updated} matched & updated"
                    f" ({elapsed:.0f}s elapsed)\n"
                )

            inv = local_map.get(stripe_inv.id)
            if inv is None:
                continue

            try:
                url = getattr(stripe_inv, "hosted_invoice_url", "") or ""
                if not url:
                    skipped += 1
                    continue
                inv.hosted_invoice_url = url
                batch.append(inv)
                updated += 1

                if len(batch) >= BATCH_SIZE:
                    if not dry_run:
                        Invoice.objects.bulk_update(
                            batch,
                            ["hosted_invoice_url"],
                            batch_size=BATCH_SIZE,
                        )
                    batch = []
            except stripe.StripeError as exc:
                logger.warning(
                    "[BACKFILL] Error processing invoice %s: %s",
                    stripe_inv.id,
                    exc,
                )
                errors += 1

        # Flush remaining batch
        if batch and not dry_run:
            Invoice.objects.bulk_update(
                batch,
                ["hosted_invoice_url"],
                batch_size=BATCH_SIZE,
            )

        elapsed = time.monotonic() - start
        self.stdout.write(
            f"  Invoices done: {updated} updated, {skipped} skipped"
            f" (no URL), {errors} errors."
            f" Scanned {fetched} Stripe records in {elapsed:.0f}s.\n"
        )
