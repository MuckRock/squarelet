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
from squarelet.organizations.models import Membership, Organization
from squarelet.users.models import User
from squarelet.users.serializers import UserWriteSerializer

BUCKET = os.environ["IMPORT_BUCKET"]
IMPORT_DIR = os.environ["IMPORT_DIR"]
ACCESS_KEY = os.environ["IMPORT_AWS_ACCESS_KEY_ID"]
SECRET_KEY = os.environ["IMPORT_AWS_SECRET_ACCESS_KEY"]


class Command(BaseCommand):
    """Import users and orgs from DocumentCloud"""

    def add_arguments(self, parser):
        parser.add_argument("organization", type=int, help="Organization ID to import")
        parser.add_argument(
            "--dry_run", action="store_true", help="Do not commit to database"
        )

    def handle(self, *args, **kwargs):
        org_id = kwargs["organization"]
        dry_run = kwargs["dry_run"]
        self.bucket_path = (
            f"s3://{ACCESS_KEY}:{SECRET_KEY}@{BUCKET}/"
            f"{IMPORT_DIR}/organization-{org_id}/"
        )
        with transaction.atomic():
            sid = transaction.savepoint()
            # we initialize the cache invalidation set here in order to
            # not send a cache invalidation for users and orgs during the
            # import
            init_cache_invalidation_set()
            organization, created = self.import_org()
            self.import_users(organization)

            if created:
                organization.set_receipt_emails(
                    [
                        u.email
                        for u in organization.users.filter(memberships__admin=True)
                    ]
                )
            if organization.user_count() > organization.max_users:
                if not organization.plan or organization.plan.free:
                    organization.max_users = organization.user_count()
                    organization.save()
                else:
                    self.stdout.write(
                        f"WARNING: Organization {organization.name} "
                        f"({organization.pk}) has {organization.user_count()} users, "
                        f"but max users is {organization.max_users} with plan "
                        f"{organization.plan}"
                    )
            # we do not send the batched invalidations, but just delete them
            delete_cache_invalidation_set()

            if dry_run:
                self.stdout.write("Dry run, not commiting changes")
                transaction.savepoint_rollback(sid)

    def import_org(self):
        self.stdout.write(f"Begin Organization Import {timezone.now()}")
        with smart_open(
            f"{self.bucket_path}organizations.csv", "r"
        ) as infile, smart_open(
            f"{self.bucket_path}organizations_map.csv", "w"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            fields = next(reader)
            uuid = fields[8]
            if uuid:
                created = False
                org = Organization.objects.get(uuid=uuid)
                org.verified_journalist = True
                org.save()
                self.stdout.write(f"Merging {fields[1]} into {org.name}")
            else:
                created = True
                self.stdout.write(f"Creating {fields[1]}")
                org = Organization.objects.create(
                    name=fields[1],
                    slug=fields[2],
                    individual=False,
                    private=fields[9] == "t",
                    verified_journalist=True,
                    created_at=parse(fields[3]).replace(tzinfo=pytz.UTC),
                    updated_at=parse(fields[4]).replace(tzinfo=pytz.UTC),
                )
            writer.writerow([fields[0], org.uuid])
        self.stdout.write(f"End Organization Import {timezone.now()}")
        return org, created

    def import_users(self, organization):
        print(f"Begin User Import {timezone.now()}")
        with smart_open(f"{self.bucket_path}users.csv", "r") as infile, smart_open(
            f"{self.bucket_path}users_map.csv", "w"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            for user in reader:
                # 3 is reviewer - should not have been exported
                assert user[10] != "3", f"Found a rogue reviewer, {user[0]}"

                email = (
                    EmailAddress.objects.filter(email__iexact=user[3])
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
                        username=UserWriteSerializer.unique_username(user[1] + user[2]),
                        email=user[3],
                        name=f"{user[1]} {user[2]}",
                        is_staff=False,
                        is_active=True,
                        is_superuser=False,
                        email_failed=False,
                        is_agency=False,
                        use_autologin=True,
                        source="documentcloud",
                        created_at=parse(user[5]).replace(tzinfo=pytz.UTC),
                        updated_at=parse(user[6]).replace(tzinfo=pytz.UTC),
                    )
                    user_obj.password = "bcrypt$" + user[4]
                    user_obj.save()
                    EmailAddress.objects.create(
                        user=user_obj, email=user[3], verified=True, primary=True
                    )

                if user[10] not in ("0", "4"):
                    # 0 is disabled - do not add to organization
                    # 4 is freelancer - do not add to organization
                    if not created and organization.has_member(user_obj):
                        self.stdout.write("Already a member")
                    else:
                        self.stdout.write("Adding to organization")
                        Membership.objects.create(
                            user=user_obj,
                            organization=organization,
                            # 1 is admin
                            admin=user[10] == "1",
                        )
                else:
                    self.stdout.write("Not adding disabled/freelancer to organization")
                    user_obj.individual_organization.verified_journalist = True
                    user_obj.individual_organization.save()

                writer.writerow(
                    [
                        user[0],
                        user_obj.uuid,
                        user_obj.username,
                        user_obj.individual_organization.slug,
                        created,
                    ]
                )
