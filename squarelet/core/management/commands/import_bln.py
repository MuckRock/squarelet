# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Standard Library
import csv
import os

# Third Party
import pytz
from allauth.account.models import EmailAddress
from dateutil.parser import parse
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.oidc.middleware import (
    delete_cache_invalidation_set,
    init_cache_invalidation_set,
)
from squarelet.users.models import User
from squarelet.users.serializers import UserWriteSerializer

BUCKET = os.environ["IMPORT_BUCKET"]


class Command(BaseCommand):
    """Import users from BigLocalNews"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry_run", action="store_true", help="Do not commit to database"
        )

    def handle(self, *args, **kwargs):
        # pylint: disable=unused-argument
        dry_run = kwargs["dry_run"]

        with transaction.atomic():
            sid = transaction.savepoint()
            init_cache_invalidation_set()
            self.import_users()
            delete_cache_invalidation_set()
            if dry_run:
                self.stdout.write("Dry run, not commiting changes")
                transaction.savepoint_rollback(sid)

    def import_users(self):
        print("Begin User Import {}".format(timezone.now()))
        with smart_open(
            f"s3://{BUCKET}/bln_export/users.csv", "r"
        ) as infile, smart_open(f"s3://{BUCKET}/bln_export/log.csv", "w") as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            for i, user in enumerate(reader):
                # pylint: disable=no-else-continue
                if i % 1000 == 0:
                    print("User {} - {}".format(i, timezone.now()))
                if EmailAddress.objects.filter(email__iexact=user[5]).exists():
                    print("[User] Skipping a duplicate email: {}".format(user[5]))
                    if not User.objects.filter(email__iexact=user[5]).exists():
                        print(
                            "[User] !!! NOT THE USERS MAIN EMAIL !!!: {}".format(
                                user[5]
                            )
                        )
                    writer.writerow([user[5], user[3], "exists"])
                    continue
                else:
                    writer.writerow([user[5], user[3], "new"])
                new_username = UserWriteSerializer.unique_username(user[4])
                if new_username != user[4]:
                    print(
                        "[User] Non-unique username found: {} -> {}".format(
                            user[4], new_username
                        )
                    )
                user_obj = User.objects.create_user(
                    username=new_username,
                    email=user[5],
                    name=user[3],
                    is_staff=False,
                    is_active=True,
                    is_superuser=False,
                    email_failed=False,
                    is_agency=False,
                    use_autologin=True,
                    source="biglocalnews",
                    created_at=parse(user[0]).replace(tzinfo=pytz.UTC),
                    updated_at=parse(user[1]).replace(tzinfo=pytz.UTC),
                )
                EmailAddress.objects.create(
                    user=user_obj, email=user[5], verified=True, primary=True
                )
        print("End User Import {}".format(timezone.now()))
