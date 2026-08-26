# Django
from django.core.management.base import BaseCommand

# Standard Library
import time

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.payment import SubscriptionItem
from squarelet.organizations.payments.factory import get_payment_provider


class Command(BaseCommand):
    """Sync local SubscriptionItem fields from Stripe.

    Fetches the live Stripe subscription for each local record and updates
    stripe_status and current_period_end.  Safe to re-run — skips records
    without a subscription_id and continues past individual Stripe errors.
    """

    help = "Sync current_period_end from Stripe for all subscriptions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            default=None,
            help="Limit to a single organization slug",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without saving",
        )

    def handle(self, *args, **options):
        org_filter = options["org"]
        dry_run = options["dry_run"]

        qs = SubscriptionItem.objects.select_related("plan", "organization").exclude(
            subscription_id=None
        )
        if org_filter:
            qs = qs.filter(organization__slug=org_filter)

        total = qs.count()
        self.stdout.write(f"Syncing {total} subscription(s)...\n")

        sub_svc = get_payment_provider().get_subscription_service()

        updated = skipped = errors = 0
        start = time.monotonic()

        for local_sub in qs.iterator():
            result = self._sync_one(sub_svc, local_sub, dry_run)
            if result == "updated":
                updated += 1
            elif result == "skipped":
                skipped += 1
            else:
                errors += 1

        elapsed = time.monotonic() - start
        self.stdout.write(
            f"\nDone in {elapsed:.1f}s — "
            f"updated: {updated}, unchanged: {skipped}, errors: {errors}\n"
        )

    def _sync_one(self, sub_svc, local_sub, dry_run):
        """Sync CPE for one subscription; return 'updated', 'skipped', or 'error'."""
        try:
            stripe_sub = sub_svc.retrieve(local_sub.subscription_id)
        except stripe.InvalidRequestError as exc:
            self.stdout.write(
                f"  [ERROR] {local_sub.subscription_id} "
                f"({local_sub.organization.slug}): {exc}\n"
            )
            return "error"

        old_cpe = local_sub.current_period_end
        local_sub.cache_stripe_subscription_fields(stripe_sub)

        if local_sub.current_period_end == old_cpe:
            return "skipped"

        self.stdout.write(
            f"  {'[DRY RUN] ' if dry_run else ''}"
            f"{local_sub.organization.slug} ({local_sub.subscription_id})\n"
            f"    current_period_end: {old_cpe} → {local_sub.current_period_end}\n"
        )
        if not dry_run:
            local_sub.save(update_fields=["current_period_end"])
        return "updated"
