# Django
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# Standard Library
import json
from datetime import datetime, timedelta

# Third Party
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from oidc_provider.models import Client, ResponseType

# Squarelet
from squarelet.oidc.models import ClientProfile
from squarelet.organizations.choices import RelationshipType
from squarelet.organizations.models import (
    Membership,
    Organization,
    OrganizationChangeLog,
)
from squarelet.organizations.models.invitation import Invitation, OrganizationInvitation
from squarelet.organizations.models.payment import (
    Customer,
    PaymentMethod,
    Plan,
    Subscription,
    SubscriptionItem,
)
from squarelet.users.models import User

E2E_PASSWORD = "e2e-test-password"

OIDC_CLIENT_ID = "e2e-verify-client"
OIDC_REDIRECT_URL = "https://dev.squarelet.com/"

USERS = [
    {"username": "e2e-staff", "is_staff": True},
    {"username": "e2e-admin", "is_staff": False},
    {"username": "e2e-member", "is_staff": False},
    {"username": "e2e-regular", "is_staff": False},
    {"username": "e2e-requester", "is_staff": False},
    {"username": "e2e-unverified", "is_staff": False, "verified": False},
    # Sole admin of e2e-leave-org, used for the leave/reassign-admin flow
    {"username": "e2e-lone-admin", "is_staff": False},
    # Non-admin member of e2e-leave-org, removed by the leave flow
    {"username": "e2e-leave-member", "is_staff": False},
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
    {
        "name": "e2e-collective-org",
        "slug": "e2e-collective-org",
        "private": False,
        "verified_journalist": True,
        "max_users": 20,
        "admins": ["e2e-admin"],
        "members": [],
        "collective_enabled": True,
    },
    {
        # Dedicated org for the leave / reassign-admin flow. e2e-lone-admin is
        # the sole admin so leaving triggers the reassign form; the members are
        # candidates the outgoing admin can promote.
        "name": "e2e-leave-org",
        "slug": "e2e-leave-org",
        "private": False,
        "verified_journalist": True,
        "max_users": 20,
        "admins": ["e2e-lone-admin"],
        "members": ["e2e-member", "e2e-leave-member"],
    },
]

# Extra state for the visual snapshots in e2e/visual.spec.ts, seeded only for
# that spec so the behavioural specs keep their free, empty organizations.
VISUAL_USERS = [
    # Admin of e2e-visual-org; both it and the user's own org are subscribed
    "e2e-visual-member",
    # Has a pending invitation, so onboarding stops at the join_org step
    "e2e-visual-joiner",
    # Never prompted for MFA, so onboarding stops at the MFA opt-in step
    "e2e-visual-onboard",
    # Has a TOTP authenticator with VISUAL_TOTP_SECRET
    "e2e-visual-mfa",
]

VISUAL_ORG = "e2e-visual-org"

# Must match TOTP_SECRET in e2e/helpers.ts
VISUAL_TOTP_SECRET = "JBSWY3DPEHPK3PXP"

BENEFITS = [
    "Unlimited private documents",
    "50 monthly requests",
    "Priority support",
    "Shared resources across your team",
]

VISUAL_PLANS = {
    "e2e-visual-team-plan": {
        "name": "E2E Team",
        "for_individuals": False,
        "for_groups": True,
        "base_price": 100,
        "price_per_user": 10,
        "minimum_users": 5,
    },
    "sunlight-essential": {
        "name": "Sunlight Essential",
        "product": "sunlight",
        "wix": True,
        "base_price": 50,
    },
    "sunlight-essential-annual": {
        "name": "Sunlight Essential (Annual)",
        "product": "sunlight",
        "wix": True,
        "annual": True,
        "base_price": 500,
    },
    "sunlight-enterprise": {
        "name": "Sunlight Enterprise",
        "product": "sunlight",
        "wix": True,
    },
}


def fixed_date(year, month, day):
    """Dates on the page must not move between the baseline and the comparison."""
    return timezone.make_aware(datetime(year, month, day, 12))


class Command(BaseCommand):
    help = "Seed or teardown E2E test data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--action",
            choices=[
                "seed",
                "teardown",
                "clear_invitations",
                "seed_visual",
                "teardown_visual",
            ],
            required=True,
            help="Whether to seed, teardown, or clear invitation test data",
        )

    def handle(self, *args, **options):
        action = options["action"]
        if action == "seed":
            self.seed()
        elif action == "teardown":
            self.teardown()
        elif action == "clear_invitations":
            self.clear_invitations()
        elif action == "seed_visual":
            self.seed_visual()
        elif action == "teardown_visual":
            self.teardown_visual()

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

        # Create a free group plan for e2e purchase redirect tests
        Plan.objects.get_or_create(
            slug="e2e-test-plan",
            defaults={
                "name": "E2E Test Plan",
                "minimum_users": 1,
                "base_price": 0,
                "price_per_user": 0,
                "for_individuals": False,
                "for_groups": True,
                "public": True,
            },
        )

        # Create the professional plan (referenced by the user detail view
        # as the individual upgrade option)
        Plan.objects.get_or_create(
            slug="professional",
            defaults={
                "name": "Professional",
                "minimum_users": 1,
                "base_price": 20,
                "price_per_user": 5,
                "for_individuals": True,
                "for_groups": False,
            },
        )

        # Create users
        created_users = {}
        for user_spec in USERS:
            username = user_spec["username"]

            if User.objects.filter(username=username).exists():
                self.stderr.write(f"User {username} already exists, skipping")
                created_users[username] = User.objects.get(username=username)
                continue

            created_users[username] = self._create_user(
                username,
                is_staff=user_spec["is_staff"],
                verified=user_spec.get("verified", True),
            )
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
                collective_enabled=org_spec.get("collective_enabled", False),
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

        # Create an OIDC client that gates features behind verification
        self._seed_verification_client()

        # Output metadata as JSON for Playwright to consume
        result = {
            "users": [u["username"] for u in USERS],
            "orgs": [o["slug"] for o in ORGS],
            "password": E2E_PASSWORD,
        }
        self.stdout.write(json.dumps(result))

    def _create_user(self, username, is_staff=False, verified=True):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=E2E_PASSWORD,
            is_staff=is_staff,
        )

        # create_user already creates the individual org and membership
        # via Organization.objects.create_individual, but we still need
        # a verified EmailAddress for allauth login
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=verified,
        )

        # Set last_mfa_prompt so the MFA onboarding step is snoozed,
        # preventing onboarding from intercepting login redirects
        user.last_mfa_prompt = timezone.now()
        user.save(update_fields=["last_mfa_prompt"])
        return user

    def _seed_verification_client(self):
        """Create a confidential OIDC client with verification gating enabled."""
        if Client.objects.filter(client_id=OIDC_CLIENT_ID).exists():
            self.stderr.write(f"OIDC client {OIDC_CLIENT_ID} already exists, skipping")
            return

        code_type, _ = ResponseType.objects.get_or_create(
            value="code", defaults={"description": "Authorization Code Flow"}
        )
        client = Client.objects.create(
            name="E2E Verify App",
            client_id=OIDC_CLIENT_ID,
            client_secret="e2e-verify-secret",
            client_type="confidential",
            require_consent=False,
            reuse_consent=True,
            _redirect_uris=OIDC_REDIRECT_URL,
            _scope="openid profile email",
        )
        client.response_types.add(code_type)
        ClientProfile.objects.create(
            client=client,
            checks_verification=True,
            verification_notice="Uploading documents requires a verified newsroom.",
        )
        self.stderr.write(f"Created OIDC client: {OIDC_CLIENT_ID}")

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
    def clear_invitations(self):
        """Delete all invitations for e2e test organizations and reset
        memberships back to the seeded state."""
        count, _ = Invitation.objects.filter(
            organization__slug__startswith="e2e-"
        ).delete()
        self.stderr.write(f"Deleted {count} invitation-related objects")

        # Clear organization-to-organization invitations and member-org
        # relationships so member-org management tests start from a clean slate
        count, _ = OrganizationInvitation.objects.filter(
            from_organization__slug__startswith="e2e-"
        ).delete()
        count2, _ = OrganizationInvitation.objects.filter(
            to_organization__slug__startswith="e2e-"
        ).delete()
        self.stderr.write(f"Deleted {count + count2} organization invitation objects")
        for org in Organization.objects.filter(
            slug__startswith="e2e-", individual=False
        ):
            org.members.clear()

        # Reset memberships to seeded state (remove members added during tests)
        for org_spec in ORGS:
            seeded_usernames = org_spec["admins"] + org_spec["members"]
            count, _ = (
                Membership.objects.filter(
                    organization__slug=org_spec["slug"],
                )
                .exclude(
                    user__username__in=seeded_usernames,
                )
                .delete()
            )
            if count:
                self.stderr.write(
                    f"Removed {count} non-seeded memberships from {org_spec['slug']}"
                )

        self.stdout.write(json.dumps({"status": "clear_invitations_complete"}))

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

        # Delete the seeded OIDC client (cascades to its ClientProfile)
        count, _ = Client.objects.filter(client_id=OIDC_CLIENT_ID).delete()
        if count:
            self.stderr.write(f"Deleted OIDC client {OIDC_CLIENT_ID}")

        # Delete Staff group created by seed
        count, _ = Group.objects.filter(name="Staff").delete()
        if count:
            self.stderr.write("Deleted Staff group")

        self.stderr.write("Teardown complete")
        self.stdout.write(json.dumps({"status": "teardown_complete"}))

    @transaction.atomic
    def seed_visual(self):
        """Replace the visual-snapshot state; prints the invitation uuids."""
        self.teardown_visual()

        Plan.objects.filter(slug__in=["professional", "organization"]).update(
            benefits=BENEFITS
        )
        plans = {
            slug: self._get_or_create_plan(slug, **fields)
            for slug, fields in VISUAL_PLANS.items()
        }

        users = {username: self._create_user(username) for username in VISUAL_USERS}
        User.objects.filter(username="e2e-visual-onboard").update(last_mfa_prompt=None)
        Authenticator.objects.create(
            user=users["e2e-visual-mfa"],
            type=Authenticator.Type.TOTP,
            data={"secret": VISUAL_TOTP_SECRET},
        )
        User.objects.filter(
            username__in=[u["username"] for u in USERS] + VISUAL_USERS
        ).update(created_at=fixed_date(2024, 3, 1))

        member = users["e2e-visual-member"]
        org = Organization.objects.create(
            name="E2E Visual Newsroom",
            slug=VISUAL_ORG,
            verified_journalist=True,
            max_users=5,
            individual=False,
        )
        Membership.objects.create(user=member, organization=org, admin=True)

        self._subscribe(
            member.individual_organization, [Plan.objects.get(slug="professional")]
        )
        self._subscribe(
            org, [plans["e2e-visual-team-plan"], plans["sunlight-essential"]]
        )

        public_org = Organization.objects.get(slug="e2e-public-org")
        private_org = Organization.objects.get(slug="e2e-private-org")
        regular = User.objects.get(username="e2e-regular")
        requester = User.objects.get(username="e2e-requester")
        member_invitation = Invitation.objects.create(
            organization=public_org, email=member.email, user=member
        )
        invitations = [
            member_invitation,
            Invitation.objects.create(
                organization=public_org,
                email=users["e2e-visual-joiner"].email,
                user=users["e2e-visual-joiner"],
            ),
            Invitation.objects.create(
                organization=private_org, user=member, email=member.email, request=True
            ),
            Invitation.objects.create(
                organization=public_org,
                user=member,
                email=member.email,
                request=True,
                rejected_at=fixed_date(2024, 4, 2),
            ),
            Invitation.objects.create(organization=org, email="invitee@example.com"),
            Invitation.objects.create(
                organization=org,
                user=regular,
                email=regular.email,
                accepted_at=fixed_date(2024, 4, 3),
            ),
            Invitation.objects.create(
                organization=org,
                user=requester,
                email=requester.email,
                request=True,
            ),
        ]
        # A minute apart, so tables sorted by date keep one order.
        for minute, invitation in enumerate(invitations):
            Invitation.objects.filter(pk=invitation.pk).update(
                created_at=fixed_date(2024, 4, 1) + timedelta(minutes=minute)
            )

        group_invitation = OrganizationInvitation.objects.create(
            from_user=User.objects.get(username="e2e-admin"),
            from_organization=Organization.objects.get(slug="e2e-collective-org"),
            to_organization=org,
            relationship_type=RelationshipType.member,
        )

        self.stdout.write(
            json.dumps(
                {
                    "member_invitation": str(member_invitation.uuid),
                    "group_invitation": str(group_invitation.uuid),
                }
            )
        )

    def _get_or_create_plan(self, slug, base_price=0, price_per_user=0, **fields):
        # Creating a paid plan makes it on Stripe; pricing it afterwards does not.
        plan, _ = Plan.objects.get_or_create(
            slug=slug,
            defaults={
                "public": True,
                "benefits": BENEFITS,
                "short_description": "A plan for visual snapshots.",
                "description": "Everything a newsroom needs.\n\n- One\n- Two",
                **fields,
            },
        )
        Plan.objects.filter(pk=plan.pk).update(
            base_price=base_price, price_per_user=price_per_user
        )
        plan.refresh_from_db()
        return plan

    def _subscribe(self, organization, plans):
        """Subscribe in the database only; blank Stripe ids keep Stripe out."""
        customer = organization.customer()
        PaymentMethod.objects.create(
            customer=customer, brand="visa", last4="4242", exp_month=4, exp_year=2031
        )
        subscription = Subscription.objects.create(
            organization=organization, current_period_end=fixed_date(2030, 2, 1)
        )
        for plan in plans:
            SubscriptionItem.objects.create(subscription=subscription, plan=plan)

    @transaction.atomic
    def teardown_visual(self):
        """Remove the visual-snapshot state; the plans stay, as deleting one
        calls Stripe."""
        users = User.objects.filter(username__in=VISUAL_USERS)
        orgs = Organization.objects.filter(
            Q(slug=VISUAL_ORG) | Q(individual=True, users__in=users)
        )
        Invitation.objects.filter(user__in=users).delete()
        OrganizationChangeLog.objects.filter(
            Q(user__in=users) | Q(organization__in=orgs)
        ).delete()
        org_pks = list(orgs.values_list("pk", flat=True))
        users.delete()
        Organization.objects.filter(pk__in=org_pks).delete()
        Plan.objects.filter(slug__in=["professional", "organization"]).update(
            benefits=[]
        )
