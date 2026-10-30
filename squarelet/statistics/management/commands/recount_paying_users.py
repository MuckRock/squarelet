# Django
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
from datetime import date

# Squarelet
from squarelet.statistics.models import Statistics
from squarelet.statistics.tasks import paying_users
from squarelet.users.models import User


def on_plan(slug):
    """Who the digest counted before comps were excluded, a user per line."""
    return User.objects.filter(organizations__subscriptions__plans__slug=slug)


class Command(BaseCommand):
    """Take comped users out of the paying-user statistics stored since a date.

    Only comps come out, so each day's gained and lost Pro users survive.  A
    row holding no comped Pro user is skipped, which makes a re-run, or a date
    before the overcount began, change nothing.
    """

    help = "Remove comped users from stored Pro and Organization statistics"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=date.fromisoformat,
            required=True,
            help="First stored date to correct (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing anything",
        )

    def handle(self, *args, **options):
        comped_pro = set(
            on_plan("professional")
            .exclude(pk__in=paying_users("professional"))
            .values_list("pk", flat=True)
        )
        org_overcount = (
            on_plan("organization").count() - paying_users("organization").count()
        )

        with transaction.atomic():
            for stats in Statistics.objects.filter(date__gte=options["since"]).order_by(
                "date"
            ):
                self._correct(stats, comped_pro, org_overcount)
            if options["dry_run"]:
                self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))
                transaction.set_rollback(True)

    def _correct(self, stats, comped_pro, org_overcount):
        comped = stats.pro_users.filter(pk__in=comped_pro)
        if not comped.exists():
            self.stdout.write(f"{stats.date}: no comped users, skipped")
            return
        stats.pro_users.remove(*comped)
        pro = stats.pro_users.count()
        org = stats.total_users_org - org_overcount
        self.stdout.write(
            f"{stats.date}: pro {stats.total_users_pro} -> {pro}, "
            f"org {stats.total_users_org} -> {org}"
        )
        stats.total_users_pro = pro
        stats.total_users_org = org
        stats.save(update_fields=["total_users_pro", "total_users_org"])
