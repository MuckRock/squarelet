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

user_uuid2pk = {}
org_uuid2pk = {}


class Command(BaseCommand):
    """Import users and orgs from MuckRock"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--date_joined", action="store_true", help="Only import date joined data"
        )

    def handle(self, *args, **kwargs):
        # pylint: disable=unused-argument
        if kwargs["date_joined"]:
            with transaction.atomic():
                self.import_date_joined()
        else:
            with transaction.atomic():
                self.import_orgs()
                self.import_users()
                self.import_members()

    def import_users(self):
        print("Begin User Import {}".format(timezone.now()))
        with smart_open(f"s3://{BUCKET}/squarelet_export/users.csv", "r") as infile:
            reader = csv.reader(infile)
            next(reader)  # discard headers
            for i, user in enumerate(reader):
                if i % 1000 == 0:
                    print("User {} - {}".format(i, timezone.now()))
                # skip non unique emails
                # all emails should be unqiue before official migration
                # but dont skip blank emails
                if user[2] and User.objects.filter(email=user[2]).exists():
                    print("[User] Skipping a duplicate email: {}".format(user[2]))
                    continue
                user_obj = User.objects.create(
                    individual_organization_id=UUID(user[0]),
                    username=user[1],
                    email=user[2] if user[2] else None,
                    password=user[3],
                    name=user[4],
                    is_staff=user[5] == "True",
                    is_active=user[6] == "True",
                    is_superuser=user[7] == "True",
                    email_failed=user[9] == "True",
                    is_agency=user[10] == "True",
                    avatar=user[11],
                    use_autologin=user[12] == "True",
                    source=user[13],
                )
                user_uuid2pk[user[0]] = user_obj.pk
                if user_obj.email:
                    EmailAddress.objects.create(
                        user=user_obj,
                        email=user_obj.email,
                        primary=True,
                        verified=user[8] == "True",
                    )
        print("End User Import {}".format(timezone.now()))

    def import_orgs(self):
        print("Begin Organization Import {}".format(timezone.now()))
        plans = {p.slug: p for p in Plan.objects.all()}
        with smart_open(f"s3://{BUCKET}/squarelet_export/orgs.csv", "r") as infile:
            reader = csv.reader(infile)
            next(reader)  # discard headers
            for i, org in enumerate(reader):
                if i % 1000 == 0:
                    print("Org {} - {}".format(i, timezone.now()))
                plan = plans[org[3]]
                org_obj = Organization.objects.create(
                    uuid=org[0],
                    name=org[1],
                    slug=org[2],
                    plan=plan,
                    next_plan=plan,
                    individual=org[4] == "True",
                    private=org[5] == "True",
                    customer_id=org[6] if org[6] else None,
                    subscription_id=org[7] if org[7] else None,
                    payment_failed=org[8] == "True",
                    update_on=org[9],
                    max_users=int(org[10]),
                    avatar=org[12],
                )
                org_obj.set_receipt_emails(e for e in org[11].split(",") if e)
                org_uuid2pk[org[0]] = org_obj.pk
        print("End Organization Import {}".format(timezone.now()))

    def import_members(self):
        print("Begin Member Import {}".format(timezone.now()))
        with smart_open(f"s3://{BUCKET}/squarelet_export/members.csv", "r") as infile:
            reader = csv.reader(infile)
            next(reader)  # discard headers
            for i, member in enumerate(reader):
                if i % 1000 == 0:
                    print("Member {} - {}".format(i, timezone.now()))
                # skip users we skipped above
                if not User.objects.filter(
                    individual_organization_id=member[0]
                ).exists():
                    print("[Member] Skipping a missing user: {}".format(member[0]))
                    continue
                Membership.objects.create(
                    user_id=user_uuid2pk[member[0]],
                    organization_id=org_uuid2pk[member[1]],
                    admin=member[4] == "True",
                )
        print("End Member Import {}".format(timezone.now()))

    def import_date_joined(self):
        print("Begin Date Joined Import {}".format(timezone.now()))
        with smart_open(
            f"s3://{BUCKET}/squarelet_export/date_joined.csv", "r"
        ) as infile:
            reader = csv.reader(infile)
            next(reader)  # discard headers
            for i, user in enumerate(reader):
                if i % 1000 == 0:
                    print("User {} - {}".format(i, timezone.now()))
                try:
                    user_ = User.objects.get(individual_organization_id=UUID(user[0]))
                except User.DoesNotExist:
                    print(f"ERROR: User {user[0]} does not exist")
                else:
                    created_at = parse(user[1])
                    if user_.created_at > created_at:
                        user_.created_at = created_at
                        user_.save()
        print("End User Import {}".format(timezone.now()))
