# Django
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

# Standard Library
import json

# Squarelet
from squarelet.statistics.models import Statistics

# The fields exported for each day. Keep this in sync with the KPI dashboard,
# which reads these keys directly.
DAY_FIELDS = [
    "total_users",
    "total_users_excluding_agencies",
    "total_users_pro",
    "total_users_org",
    "total_users_mfa",
    "total_orgs",
    "verified_orgs",
]

# Default location within the default storage backend. In production this is
# the S3/MinIO bucket, so the resulting object has a fetchable URL.
DEFAULT_STORAGE_KEY = "kpi/kpi_stats.json"


class Command(BaseCommand):
    """Export nightly Statistics as JSON for the KPI dashboard.

    Writes a single JSON document with a ``days`` array, one entry per
    ``Statistics`` row, ordered oldest to newest. Output can go to stdout,
    a local file, or the default storage backend (which yields a public URL
    the dashboard can fetch).
    """

    help = "Export nightly statistics as JSON for the KPI dashboard."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Only export the most recent N days (default: all).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Write JSON to this local file path instead of stdout.",
        )
        parser.add_argument(
            "--storage",
            nargs="?",
            const=DEFAULT_STORAGE_KEY,
            default=None,
            metavar="KEY",
            help=(
                "Write JSON to the default storage backend at KEY "
                f"(default: {DEFAULT_STORAGE_KEY}) and print its URL."
            ),
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=None,
            help="Pretty-print JSON with this indent (default: compact).",
        )

    def build_payload(self, days=None):
        # Annotate the daily-active count from the users_today M2M in a single
        # query rather than one query per row.
        queryset = (
            Statistics.objects.annotate(active_users=Count("users_today"))
            .order_by("date")
        )
        rows = list(queryset)
        if days is not None:
            rows = rows[-days:]

        day_data = []
        for row in rows:
            entry = {"date": row.date.isoformat()}
            for field in DAY_FIELDS:
                entry[field] = getattr(row, field)
            entry["users_today"] = row.active_users
            day_data.append(entry)

        return {
            "generated_at": timezone.now().isoformat(),
            "source": "squarelet.statistics.Statistics",
            "sample": False,
            "count": len(day_data),
            "days": day_data,
        }

    def handle(self, *args, **options):
        payload = self.build_payload(days=options["days"])
        text = json.dumps(payload, indent=options["indent"])

        wrote_somewhere = False

        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as out_file:
                out_file.write(text)
            self.stderr.write(
                self.style.SUCCESS(
                    f"Wrote {payload['count']} days to {options['output']}"
                )
            )
            wrote_somewhere = True

        if options["storage"]:
            key = options["storage"]
            if default_storage.exists(key):
                default_storage.delete(key)
            default_storage.save(key, ContentFile(text.encode("utf-8")))
            self.stderr.write(
                self.style.SUCCESS(
                    f"Wrote {payload['count']} days to storage: {key}"
                )
            )
            self.stdout.write(default_storage.url(key))
            wrote_somewhere = True

        if not wrote_somewhere:
            # Default: emit JSON on stdout so it can be piped or captured.
            self.stdout.write(text)
