# Django
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
import json

# Third Party
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.organizations.models import Membership, Organization
from squarelet.organizations.models.payment import Customer, Plan
from squarelet.users.models import User

E2E_PASSWORD = "e2e-test-password"

USERS = [
    {"username": "e2e-staff", "is_staff": True},
    {"username": "e2e-admin", "is_staff": False},
    {"username": "e2e-member", "is_staff": False},
    {"username": "e2e-regular", "is_staff": False},
    {"username": "e2e-requester", "is_staff": False},
]

# DB-assigned Organization permissions for the e2e-staff user
STAFF_ORG_PERMISSIONS = [
    "change_organization",
    "can_manage_members",
    "can_view_members",
    "can_view_subscription",
    "can_edit_subscription",
    "can_view_charge",
    "can_review_profile_changes",
]

ORGS = [
    {
        "name": "e2e-public-org",
        "slug": "e2e-public-org",
        "private": False,
        "verified_journalist": True,
        "max_users": 20,
        "admins": ["e2e-admin"],
        "members": ["e2e-member"],
    },
    {
        "name": "e2e-private-org",
        "slug": "e2e-private-org",
        "private": True,
        "verified_journalist": True,
        "max_users": 20,
        "admins": ["e2e-admin"],
        "members": [],
    },
]


class Command(BaseCommand):
    help = "Seed or teardown E2E test data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--action",
            choices=["seed", "teardown"],
            required=True,
            help="Whether to seed or teardown test data",
        )

    def handle(self, *args, **options):
        action = options["action"]
        if action == "seed":
            self.seed()
        elif action == "teardown":
            self.teardown()

    @transaction.atomic
    def seed(self):
        # Create the organization plan (required by the org detail view)
        Plan.objects.get_or_create(
            slug="organization",
            defaults={
                "name": "Organization",
                "minimum_users": 1,
                "base_price": 0,
                "price_per_user": 0,
                "for_individuals": False,
                "for_groups": True,
            },
        )

        # Create users
        created_users = {}
        for user_spec in USERS:
            username = user_spec["username"]
            email = f"{username}@example.com"

            if User.objects.filter(username=username).exists():
                self.stderr.write(f"User {username} already exists, skipping")
                created_users[username] = User.objects.get(username=username)
                continue

            user = User.objects.create_user(
                username=username,
                email=email,
                password=E2E_PASSWORD,
                is_staff=user_spec["is_staff"],
            )

            # create_user already creates the individual org and membership
            # via Organization.objects.create_individual, but we still need
            # a verified EmailAddress for allauth login
            EmailAddress.objects.create(
                user=user,
                email=email,
                primary=True,
                verified=True,
            )

            created_users[username] = user
            self.stderr.write(f"Created user: {username}")

        # Create "Staff" group with org permissions and add staff user
        staff_group = self._create_staff_group()
        staff_user = created_users.get("e2e-staff")
        if staff_user:
            staff_user.groups.add(staff_group)
            self.stderr.write("Added e2e-staff to Staff group")

        # Create organizations
        created_orgs = {}
        for org_spec in ORGS:
            slug = org_spec["slug"]

            if Organization.objects.filter(slug=slug).exists():
                self.stderr.write(f"Org {slug} already exists, skipping")
                created_orgs[slug] = Organization.objects.get(slug=slug)
                continue

            org = Organization.objects.create(
                name=org_spec["name"],
                slug=slug,
                private=org_spec["private"],
                verified_journalist=org_spec["verified_journalist"],
                max_users=org_spec["max_users"],
                individual=False,
            )

            # Create a Customer record (required for plan/billing sections)
            Customer.objects.create(organization=org)

            # Add admins
            for admin_username in org_spec["admins"]:
                user = created_users[admin_username]
                Membership.objects.create(user=user, organization=org, admin=True)

            # Add members
            for member_username in org_spec["members"]:
                user = created_users[member_username]
                Membership.objects.create(user=user, organization=org, admin=False)

            created_orgs[slug] = org
            self.stderr.write(f"Created org: {slug}")

        # Output metadata as JSON for Playwright to consume
        result = {
            "users": [u["username"] for u in USERS],
            "orgs": [o["slug"] for o in ORGS],
            "password": E2E_PASSWORD,
        }
        self.stdout.write(json.dumps(result))

    def _create_staff_group(self):
        """Create a Staff group with Organization-level permissions."""
        group, created = Group.objects.get_or_create(name="Staff")
        if created:
            org_content_type = ContentType.objects.get_for_model(Organization)
            perms = Permission.objects.filter(
                codename__in=STAFF_ORG_PERMISSIONS, content_type=org_content_type
            )
            group.permissions.set(perms)
            self.stderr.write(
                f"Created Staff group with {perms.count()} org permissions"
            )
        else:
            self.stderr.write("Staff group already exists, skipping")
        return group

    @transaction.atomic
    def teardown(self):
        # Delete users (cascades to memberships, email addresses)
        count, _ = User.objects.filter(username__startswith="e2e-").delete()
        self.stderr.write(f"Deleted {count} user-related objects")

        # Delete non-individual orgs (cascades to memberships, customers)
        count, _ = Organization.objects.filter(
            slug__startswith="e2e-", individual=False
        ).delete()
        self.stderr.write(f"Deleted {count} org-related objects")

        # Delete individual orgs left behind
        count, _ = Organization.objects.filter(
            name__startswith="e2e-", individual=True
        ).delete()
        self.stderr.write(f"Deleted {count} individual org objects")

        # Delete Staff group created by seed
        count, _ = Group.objects.filter(name="Staff").delete()
        if count:
            self.stderr.write("Deleted Staff group")

        self.stderr.write("Teardown complete")
        self.stdout.write(json.dumps({"status": "teardown_complete"}))
