# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Standard Library
import csv
import os
from uuid import UUID

# Third Party
from allauth.account.models import EmailAddress
from dateutil.parser import parse
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.organizations.models import Membership, Organization, Plan
from squarelet.users.models import User

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
            self.import_users()
            if dry_run:
                self.stdout.write("Dry run, not commiting changes")
                transaction.savepoint_rollback(sid)

    def import_users(self):
        print("Begin User Import {}".format(timezone.now()))
        with smart_open(f"s3://{BUCKET}/bln_export/users.csv", "r") as infile:
            reader = csv.reader(infile)
            next(reader)  # discard headers
            for i, user in enumerate(reader):
                if i % 1000 == 0:
                    print("User {} - {}".format(i, timezone.now()))
                if User.objects.filter(email=user[5]).exists():
                    print("[User] Skipping a duplicate email: {}".format(user[5]))
                    continue
                new_username = UserWriteSerializer.unique_username(user[4])
                if new_username != user[4]:
                    print(
                        "[User] Non-unique username found: {} -> {}",
                        user[4],
                        new_username,
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
