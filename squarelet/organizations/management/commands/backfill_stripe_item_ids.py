# Django
from django.core.management.base import BaseCommand

# Standard Library
import time

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.payment import Subscription


class Command(BaseCommand):
    """Record the Stripe item id of every subscription line that lacks one.

    `SubscriptionItem.stripe_item_id` arrived empty with the
    subscription/item split: the old schema had one Stripe subscription per
    row and no per-line id to carry across, so the data migration had nothing
    to populate it from.

    An empty id is not cosmetic.  `stripe_items(include_ids=True)` omits the
    id it does not have, and a line spec with no id is how you ask Stripe to
    *add* a line - so the first modification of any subscription that
    predates the split is rejected, because the Price is already on it.

    `stripe_modify` now heals a subscription as it touches it, which means
    this is a way to fix them all at once rather than one customer at a time.
    Safe to re-run: lines that already have an id are left alone, and each
    subscription is independent, so a Stripe error on one does not stop the
    rest.
    """

    help = "Populate SubscriptionItem.stripe_item_id from Stripe"

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
            help="Report what would be filled in without saving",
        )

    def handle(self, *args, **options):
        # Only subscriptions that actually have a line missing an id: the
        # rest would cost a Stripe read to learn nothing.
        qs = (
            Subscription.objects.select_related("organization")
            .exclude(subscription_id="")
            .filter(items__stripe_item_id="")
            .distinct()
        )
        if options["org"]:
            qs = qs.filter(organization__slug=options["org"])

        self.stdout.write(f"{qs.count()} subscription(s) with unidentified lines...\n")

        counts = {"filled": 0, "skipped": 0, "errors": 0}
        start = time.monotonic()
        for subscription in qs.iterator():
            counts[self._backfill_one(subscription, options["dry_run"])] += 1
        elapsed = time.monotonic() - start

        self.stdout.write(
            f"\nDone in {elapsed:.1f}s — "
            f"filled: {counts['filled']}, skipped: {counts['skipped']}, "
            f"errors: {counts['errors']}\n"
        )

    def _backfill_one(self, subscription, dry_run):
        """Identify one subscription's lines.  Returns a key into `counts`."""
        try:
            stripe_sub = subscription.stripe_subscription
            if stripe_sub is None:
                return "skipped"
            if dry_run:
                return self._report(subscription)
            subscription.sync_stripe_item_ids(stripe_sub)
            return "filled"
        except stripe.StripeError as exc:
            # One subscription's failure must not strand the rest: this runs
            # once, after a deploy, over every organization that has one.
            self.stderr.write(f"  {subscription.organization.slug}: {exc}")
            return "errors"

    def _report(self, subscription):
        """Name the lines a real run would fill in."""
        missing = [
            item
            for item in subscription.items.select_related("plan")
            if not item.is_free and not item.stripe_item_id
        ]
        for item in missing:
            self.stdout.write(
                f"  would fill {subscription.organization.slug} / {item.plan.slug}"
            )
        return "filled" if missing else "skipped"
