# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Standard Library
import csv
import os

# Third Party
from allauth.account.models import EmailAddress
from dateutil.parser import parse
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.organizations.models import Membership, Organization, Plan
from squarelet.users.models import User

BUCKET = os.environ["IMPORT_BUCKET"]


class Command(BaseCommand):
    """Import users and orgs from DocumentCloud"""

    def add_arguments(self, parser):
        parser.add_argument("organization", type=int, help="Organization ID to import")

    def handle(self, *args, **kwargs):
        # pylint: disable=unused-argument
        org_id = kwargs["organization"]
        self.bucket_path = f"s3://{BUCKET}/documentcloud-export/organization-{org_id}/"
        with transaction.atomic():
            organization, created = self.import_org()
            self.import_users(organization)
            if created:
                organization.set_receipt_emails(
                    [
                        u.email
                        for u in organization.users.filter(memberships__admin=True)
                    ]
                )
            # XXX update max users after importing users

    def import_org(self):
        self.stdout.write("Begin Organization Import {}".format(timezone.now()))
        plan = Plan.objects.get(slug="free")
        with smart_open(
            f"{self.bucket_path}organizations.csv", "rb"
        ) as infile, smart_open(
            f"{self.bucket_path}organizations_map.csv", "wb"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            fields = next(reader)
            uuid = fields[8]
            if uuid:
                created = False
                org = Organization.objects.get(uuid=uuid)
                self.stdout.write(f"Merging {fields[1]} into {org.name}")
            else:
                created = True
                self.stdout.write(f"Creating {fields[1]}")
                org = Organization.objects.create(
                    name=fields[1],
                    slug=fields[2],
                    plan=plan,
                    next_plan=plan,
                    individual=False,
                    private=fields[9] == "t",
                    verified_journalist=True,
                    created_at=parse(fields[3]),
                    updated_at=parse(fields[4]),
                )
            writer.writerow([fields[0], org.uuid])
        self.stdout.write("End Organization Import {}".format(timezone.now()))
        return org, created

    def import_users(self, organization):
        print("Begin User Import {}".format(timezone.now()))
        with smart_open(f"{self.bucket_path}users.csv", "rb") as infile, smart_open(
            f"{self.bucket_path}users_map.csv", "wb"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            for user in reader:
                # 3 is reviewer - do not import
                if user[10] == "3":
                    self.stdout.write(f"Skipping reviewer: {user[3]}")
                    continue

                email = (
                    EmailAddress.objects.filter(email=user[3])
                    .select_related("user")
                    .first()
                )
                if email:
                    created = False
                    self.stdout.write(f"Found existing user: {user[3]}")
                    user_obj = email.user
                else:
                    created = True
                    self.stdout.write(f"Creating new user: {user[3]}")
                    user_obj = User.objects.create_user(
                        username=UserWriteSerializer.unqiue_username(user[1] + user[2]),
                        email=user[3],
                        name=f"{user[1]} {user[2]}",
                        is_staff=False,
                        is_active=True,
                        is_superuser=False,
                        email_failed=False,
                        is_agency=False,
                        use_autologin=True,
                        source="documentcloud",
                        created_at=parse(user[5]),
                        updated_at=parse(user[6]),
                    )
                    user_obj.password = "bcrypt$" + user[4]
                    user_obj.save()

                if user[10] not in ("0", "4"):
                    # 0 is disabled - do not add to organization
                    # 4 is freelancer - do not add to organization
                    if not created and organization.has_member(user_obj):
                        self.stdout.write(f"Already a member")
                    else:
                        self.stdout.write(f"Adding to organization")
                        Membership.objects.create(
                            user=user_obj,
                            organizationd=organization,
                            # 1 is admin
                            admin=user[10] == "1",
                        )

                writer.writerow([user[0], user_obj.uuid, user_obj.username])
