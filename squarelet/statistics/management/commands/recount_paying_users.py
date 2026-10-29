# Django
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
from datetime import date

# Squarelet
from squarelet.statistics.models import Statistics
from squarelet.statistics.tasks import paying_users


class Command(BaseCommand):
    """Recount the paying-user statistics stored since a date.

    Rows stored after release 5 counted comped users as paying.  Uses today's
    subscriptions, since a past day's cannot be recovered; across a few weeks
    the drift is a handful of users, against an overcount of over a thousand.
    """

    help = "Recount stored Pro and Organization user statistics since a date"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=date.fromisoformat,
            required=True,
            help="First stored date to recount (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing anything",
        )

    def handle(self, *args, **options):
        pro = paying_users("professional")
        org_count = paying_users("organization").count()
        pro_count = pro.count()

        with transaction.atomic():
            for stats in Statistics.objects.filter(date__gte=options["since"]).order_by(
                "date"
            ):
                self.stdout.write(
                    f"{stats.date}: pro {stats.total_users_pro} -> {pro_count}, "
                    f"org {stats.total_users_org} -> {org_count}"
                )
                stats.total_users_pro = pro_count
                stats.total_users_org = org_count
                stats.save(update_fields=["total_users_pro", "total_users_org"])
                stats.pro_users.set(pro)
            if options["dry_run"]:
                self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))
                transaction.set_rollback(True)
