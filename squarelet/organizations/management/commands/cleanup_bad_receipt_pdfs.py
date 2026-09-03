# Django
from django.core.management.base import BaseCommand

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.payment import Charge
from squarelet.organizations.tasks import download_receipt_pdf

PDF_MAGIC = b"%PDF-"


class Command(BaseCommand):
    """Find and fix Charges whose receipt_pdf is actually Stripe's HTML
    receipt page saved with a .pdf extension (a bug in the original
    download_receipt_pdf task, since fixed).

    For each affected Charge: deletes the bad file from storage, clears
    receipt_pdf, and re-queues download_receipt_pdf against a fresh
    receipt_url fetched from Stripe.
    """

    help = "Clear and re-download Charge receipt PDFs that are actually HTML"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report affected charges without modifying or re-queuing anything",
        )
        parser.add_argument(
            "--org",
            type=str,
            default=None,
            help="Limit to a single organization slug",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        org_filter = options["org"]

        qs = (
            Charge.objects.exclude(receipt_pdf="")
            .exclude(receipt_pdf=None)
            .select_related("organization")
        )
        if org_filter:
            qs = qs.filter(organization__slug=org_filter)

        total = bad = requeued = errors = 0
        for charge in qs.iterator():
            total += 1
            try:
                is_pdf = self._is_real_pdf(charge)
            except OSError as exc:
                errors += 1
                self.stderr.write(
                    f"[ERROR] charge {charge.pk} ({charge.charge_id}): "
                    f"could not read {charge.receipt_pdf.name!r}: {exc}\n"
                )
                continue
            if is_pdf:
                continue

            bad += 1
            self.stdout.write(
                f"[BAD] charge {charge.pk} ({charge.charge_id}) "
                f"org={charge.organization.name!r}: {charge.receipt_pdf.name}\n"
            )
            if dry_run:
                continue

            try:
                receipt_url = charge.charge.receipt_url
            except stripe.StripeError as exc:
                errors += 1
                self.stderr.write(f"  could not refetch charge from Stripe: {exc}\n")
                continue
            if not receipt_url:
                errors += 1
                self.stderr.write("  Stripe charge has no receipt_url, skipping\n")
                continue

            old_name = charge.receipt_pdf.name
            charge.receipt_pdf.delete(save=False)
            charge.receipt_pdf = None
            charge.save(update_fields=["receipt_pdf"])
            download_receipt_pdf.delay(charge.pk, receipt_url)
            requeued += 1
            self.stdout.write(f"  cleared {old_name!r}, queued re-download\n")

        self.stdout.write(
            f"\nScanned {total} charge(s) with a receipt_pdf: "
            f"{bad} bad, {requeued} re-queued, {errors} error(s).\n"
        )
        if dry_run and bad:
            self.stdout.write("(dry run - nothing was modified)\n")

    @staticmethod
    def _is_real_pdf(charge):
        """True if the stored receipt_pdf starts with a PDF file signature."""
        charge.receipt_pdf.open("rb")
        try:
            header = charge.receipt_pdf.read(len(PDF_MAGIC))
        finally:
            charge.receipt_pdf.close()
        return header.startswith(PDF_MAGIC)
