# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.utils import timezone

# Standard Library
from datetime import timedelta
from uuid import uuid4

# Third Party
import pytest
from oidc_provider.models import Client

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import (
    Entitlement,
    Invoice,
    Membership,
    Organization,
    Plan,
    Subscription,
)
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    InvoiceFactory,
    MembershipFactory,
    OrganizationFactory,
    PlanFactory,
    SubscriptionFactory,
)
from squarelet.users.tests.factories import UserFactory


class TestOrganizationQuerySet(TestCase):
    """Unit tests for Organization queryset"""

    @pytest.mark.django_db
    def test_get_viewable_staff_user(self):
        """Staff users can view all organizations"""
        staff_user = UserFactory(is_staff=True)
        private_org = OrganizationFactory(private=True, verified_journalist=False)
        public_org = OrganizationFactory(private=False, verified_journalist=True)

        viewable = Organization.objects.get_viewable(staff_user)
        assert private_org in viewable
        assert public_org in viewable
        assert viewable.count() >= 2

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_public_verified(self):
        """Authenticated users can view public, verified orgs"""
        user = UserFactory()
        public_verified_org = OrganizationFactory(
            private=False, verified_journalist=True
        )
        private_org = OrganizationFactory(private=True, verified_journalist=True)
        public_unverified_org = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_verified_org in viewable
        assert private_org not in viewable
        assert public_unverified_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_public_with_charges(self):
        """Authenticated users can view public orgs with charges"""
        user = UserFactory()
        public_org_with_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )
        ChargeFactory(organization=public_org_with_charges)
        public_org_without_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_charges in viewable
        assert public_org_without_charges not in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_public_with_paid_invoices(self):
        """Authenticated users can view public orgs with paid invoices"""
        user = UserFactory()
        public_org_with_paid_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_paid_invoice, status="paid")
        public_org_with_open_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_open_invoice, status="open")
        public_org_without_invoices = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_paid_invoice in viewable
        assert public_org_with_open_invoice not in viewable
        assert public_org_without_invoices not in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_member_of_private_org(self):
        """Authenticated users can view private orgs they are members of"""
        user = UserFactory()
        private_org = OrganizationFactory(private=True, verified_journalist=False)
        MembershipFactory(user=user, organization=private_org)
        other_private_org = OrganizationFactory(private=True, verified_journalist=False)

        viewable = Organization.objects.get_viewable(user)
        assert private_org in viewable
        assert other_private_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous_user_public_verified(self):
        """Anonymous users can only view public verified journalist orgs"""
        user = AnonymousUser()
        public_verified_org = OrganizationFactory(
            private=False, verified_journalist=True
        )
        private_verified_org = OrganizationFactory(
            private=True, verified_journalist=True
        )
        public_unverified_org = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_verified_org in viewable
        assert private_verified_org not in viewable
        assert public_unverified_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous_user_public_with_charges(self):
        """Anonymous users can view public orgs with charges"""
        user = AnonymousUser()
        public_org_with_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )
        ChargeFactory(organization=public_org_with_charges)
        public_org_without_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_charges in viewable
        assert public_org_without_charges not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous_user_public_with_paid_invoices(self):
        """Anonymous users can view public orgs with paid invoices"""
        user = AnonymousUser()
        public_org_with_paid_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_paid_invoice, status="paid")
        public_org_with_open_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_open_invoice, status="open")
        public_org_without_invoices = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_paid_invoice in viewable
        assert public_org_with_open_invoice not in viewable
        assert public_org_without_invoices not in viewable

    @pytest.mark.django_db
    def test_get_viewable_distinct_results(self):
        """Ensure queryset returns distinct results"""
        user = UserFactory()
        org = OrganizationFactory(private=False, verified_journalist=True)
        # Create a charge and membership to potentially cause duplicates
        ChargeFactory(organization=org)
        MembershipFactory(user=user, organization=org)

        viewable = Organization.objects.get_viewable(user)
        # Should only appear once despite meeting multiple criteria
        assert viewable.filter(id=org.id).count() == 1

    @pytest.mark.django_db
    def test_create_individual_basic(self):
        """Test creating an individual organization for a user"""
        user = UserFactory.build()  # build() creates unsaved instance
        assert user.pk is None  # Ensure user is unsaved as required

        org = Organization.objects.create_individual(user)

        # Verify organization properties
        assert org.name == user.username
        assert org.individual is True
        assert org.private is True
        assert org.max_users == 1

        # Verify user is saved and linked
        assert user.pk is not None
        assert user.individual_organization == org

        # Verify creator membership exists
        assert org.memberships.filter(user=user, admin=True).exists()

        # Verify change log was created
        assert org.change_logs.filter(
            reason=ChangeLogReason.created, user=user, to_plan=org.plan, to_max_users=1
        ).exists()

    @pytest.mark.django_db
    def test_create_individual_with_uuid(self):
        """Test creating an individual organization with custom UUID"""
        user = UserFactory.build()
        custom_uuid = uuid4()

        org = Organization.objects.create_individual(user, uuid=custom_uuid)

        assert org.uuid == custom_uuid
        assert org.name == user.username
        assert org.individual is True

    @pytest.mark.django_db
    def test_create_individual_returns_organization(self):
        """Test that create_individual returns the created organization"""
        user = UserFactory.build()

        org = Organization.objects.create_individual(user)

        assert isinstance(org, Organization)
        assert org == user.individual_organization


class TestFuzzySearch(TestCase):
    """Unit tests for Organization.objects.fuzzy_search()"""

    @pytest.mark.django_db
    def test_fuzzy_search_finds_similar_name(self):
        """fuzzy_search returns orgs with similar names"""
        OrganizationFactory(name="MuckRock Foundation", individual=False)
        results = Organization.objects.fuzzy_search("Muckrock")
        assert results.count() == 1
        assert results.first().name == "MuckRock Foundation"

    @pytest.mark.django_db
    def test_fuzzy_search_no_match(self):
        """fuzzy_search returns empty queryset when no orgs match"""
        OrganizationFactory(name="MuckRock Foundation", individual=False)
        results = Organization.objects.fuzzy_search("xyzzyspoon")
        assert results.count() == 0

    @pytest.mark.django_db
    def test_fuzzy_search_excludes_individual_orgs(self):
        """fuzzy_search excludes individual organizations"""
        OrganizationFactory(name="MuckRock User", individual=True, private=True)
        OrganizationFactory(name="MuckRock Foundation", individual=False)
        results = Organization.objects.fuzzy_search("MuckRock")
        assert results.count() == 1
        assert results.first().name == "MuckRock Foundation"


class TestMembershipQuerySet(TestCase):
    """Unit tests for Membership queryset"""

    @pytest.mark.django_db
    def test_get_viewable(self):
        admin, member, user = UserFactory.create_batch(3)
        private_org = OrganizationFactory(admins=[admin], private=True)
        MembershipFactory(organization=private_org, user=member)

        assert Membership.objects.get_viewable(member).count() == 3
        assert Membership.objects.get_viewable(user).count() == 1

        another_user = UserFactory()
        assert member.memberships.get_viewable(another_user).count() == 0


@pytest.mark.django_db(transaction=True)
def test_membership_create_with_wix_plan_triggers_sync(mocker):
    """Test that creating a membership with a Wix plan triggers sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    wix_plan = PlanFactory(wix=True)
    org = OrganizationFactory()
    SubscriptionFactory(organization=org, plan=wix_plan)

    # Create membership
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was called with correct parameters
    mock_sync.assert_called_once_with(org.pk, wix_plan.pk, user.pk)


@pytest.mark.django_db(transaction=True)
def test_membership_create_without_wix_plan_no_sync(mocker):
    """Test that creating a membership without Wix plan does not trigger sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    non_wix_plan = PlanFactory(wix=False)
    org = OrganizationFactory()
    SubscriptionFactory(organization=org, plan=non_wix_plan)

    # Create membership
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was NOT called
    mock_sync.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_membership_create_without_plan_no_sync(mocker):
    """Test that creating a membership for an org with no plan does not trigger sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    org = OrganizationFactory()

    # Create membership (org has no plan)
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was NOT called
    mock_sync.assert_not_called()


class TestSubscriptionQuerySet(TestCase):
    """Unit tests for Subscription queryset"""

    @pytest.mark.django_db
    def test_sunlight_active_count_zero(self):
        """Test count returns zero when no Sunlight subscriptions exist"""
        # Create some non-Sunlight subscriptions
        regular_plan = PlanFactory(slug="professional", wix=False)
        SubscriptionFactory(plan=regular_plan, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 0

    @pytest.mark.django_db
    def test_sunlight_active_count_basic(self):
        """Test count returns correct number of active Sunlight subscriptions"""
        # Create Sunlight plans
        sunlight_plan1 = PlanFactory(slug="sunlight-essential-monthly", wix=True)
        sunlight_plan2 = PlanFactory(slug="sunlight-enhanced-annual", wix=True)

        # Create active subscriptions
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan2, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 3

    @pytest.mark.django_db
    def test_sunlight_active_count_excludes_cancelled(self):
        """Test count excludes cancelled Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-essential-monthly", wix=True)

        # Create active and cancelled subscriptions
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)

        count = Subscription.objects.sunlight_active_count()
        assert count == 2

    @pytest.mark.django_db
    def test_sunlight_active_count_excludes_non_wix(self):
        """Test count excludes Sunlight plans with wix=False"""
        sunlight_wix = PlanFactory(slug="sunlight-essential-monthly", wix=True)
        sunlight_no_wix = PlanFactory(slug="sunlight-enhanced-annual", wix=False)

        SubscriptionFactory(plan=sunlight_wix, cancelled=False)
        SubscriptionFactory(plan=sunlight_no_wix, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 1

    @pytest.mark.django_db
    def test_sunlight_active_count_mixed_subscriptions(self):
        """Test count with mix of Sunlight and non-Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-essential-monthly", wix=True)
        regular_plan = PlanFactory(slug="professional", wix=False)

        # Create mix of subscriptions
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)
        SubscriptionFactory(plan=regular_plan, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 2


class TestPlanQuerySet(TestCase):
    """Unit tests for Plan queryset"""

    @pytest.mark.django_db
    def test_get_viewable_staff(self):
        """Staff users can view all plans"""

        staff_user = UserFactory(is_staff=True)
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        viewable = Plan.objects.get_viewable(staff_user)
        assert public_plan in viewable
        assert private_plan in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated(self):
        """Authenticated users can view public plans and their org plans"""

        user = UserFactory()
        org = OrganizationFactory()
        MembershipFactory(user=user, organization=org)

        public_plan = PlanFactory(public=True)
        org_plan = PlanFactory(public=False)
        # Create subscription to associate plan with org
        SubscriptionFactory(organization=org, plan=org_plan)
        unrelated_private_plan = PlanFactory(public=False)

        viewable = Plan.objects.get_viewable(user)
        assert public_plan in viewable
        assert org_plan in viewable
        assert unrelated_private_plan not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous(self):
        """Anonymous users can only view public plans"""

        anonymous = AnonymousUser()
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        viewable = Plan.objects.get_viewable(anonymous)
        assert public_plan in viewable
        assert private_plan not in viewable

    @pytest.mark.django_db
    def test_get_public(self):
        """get_public returns only public plans"""

        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        public = Plan.objects.get_public()
        assert public_plan in public
        assert private_plan not in public

    @pytest.mark.django_db
    def test_choices_for_individuals(self):
        """choices() filters for_individuals=True for individual orgs"""

        individual_org = OrganizationFactory(individual=True)
        individual_plan = PlanFactory(for_individuals=True, public=True)
        group_plan = PlanFactory(for_groups=True, for_individuals=False, public=True)

        choices = Plan.objects.choices(individual_org)
        assert individual_plan in choices
        assert group_plan not in choices

    @pytest.mark.django_db
    def test_free(self):
        """free() returns plans with zero price"""

        free_plan = PlanFactory(base_price=0, price_per_user=0)
        paid_plan = PlanFactory(base_price=500, price_per_user=0)

        free_plans = Plan.objects.free()
        assert free_plan in free_plans
        assert paid_plan not in free_plans


class TestEntitlementQuerySet(TestCase):
    """Unit tests for Entitlement queryset"""

    @pytest.mark.django_db
    def test_get_viewable_staff(self):
        """Staff users can view all entitlements"""

        staff_user = UserFactory(is_staff=True)
        client = Client.objects.create(
            name="Test Client", owner=staff_user, client_id="client-staff"
        )
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        public_entitlement = Entitlement.objects.create(
            name="Public Feature Staff", slug="public-feature-staff", client=client
        )
        public_entitlement.plans.add(public_plan)

        private_entitlement = Entitlement.objects.create(
            name="Private Feature Staff", slug="private-feature-staff", client=client
        )
        private_entitlement.plans.add(private_plan)

        viewable = Entitlement.objects.get_viewable(staff_user)
        assert public_entitlement in viewable
        assert private_entitlement in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated(self):
        """Authenticated users can view public entitlements"""

        user = UserFactory()
        other_user = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=user, client_id="client-auth1"
        )
        other_client = Client.objects.create(
            name="Other Client", owner=other_user, client_id="client-auth2"
        )
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        public_entitlement = Entitlement.objects.create(
            name="Public Feature Auth", slug="public-feature-auth", client=client
        )
        public_entitlement.plans.add(public_plan)

        private_entitlement = Entitlement.objects.create(
            name="Private Feature Auth",
            slug="private-feature-auth",
            client=other_client,
        )
        private_entitlement.plans.add(private_plan)

        viewable = Entitlement.objects.get_viewable(user)
        assert public_entitlement in viewable
        assert private_entitlement not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous(self):
        """Anonymous users can view public entitlements"""

        anonymous = AnonymousUser()
        owner = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=owner, client_id="client-anon"
        )
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        public_entitlement = Entitlement.objects.create(
            name="Public Feature Anon", slug="public-feature-anon", client=client
        )
        public_entitlement.plans.add(public_plan)

        private_entitlement = Entitlement.objects.create(
            name="Private Feature Anon", slug="private-feature-anon", client=client
        )
        private_entitlement.plans.add(private_plan)

        viewable = Entitlement.objects.get_viewable(anonymous)
        assert public_entitlement in viewable
        assert private_entitlement not in viewable

    @pytest.mark.django_db
    def test_get_public(self):
        """get_public returns only public entitlements"""

        owner = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=owner, client_id="client-public"
        )
        public_plan = PlanFactory(public=True)
        private_plan = PlanFactory(public=False)

        public_entitlement = Entitlement.objects.create(
            name="Public Feature Public", slug="public-feature-public", client=client
        )
        public_entitlement.plans.add(public_plan)

        private_entitlement = Entitlement.objects.create(
            name="Private Feature Public", slug="private-feature-public", client=client
        )
        private_entitlement.plans.add(private_plan)

        public = Entitlement.objects.get_public()
        assert public_entitlement in public
        assert private_entitlement not in public

    @pytest.mark.django_db
    def test_get_subscribed_authenticated(self):
        """Authenticated users can view entitlements they're subscribed to"""

        user = UserFactory()
        org = OrganizationFactory()
        MembershipFactory(user=user, organization=org)

        owner = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=owner, client_id="client-subscribed"
        )

        plan = PlanFactory()
        entitlement = Entitlement.objects.create(
            name="Subscribed Feature", slug="subscribed-feature-auth", client=client
        )
        entitlement.plans.add(plan)
        # Create subscription to associate plan with org
        SubscriptionFactory(organization=org, plan=plan)

        unrelated_entitlement = Entitlement.objects.create(
            name="Unrelated Feature", slug="unrelated-feature-auth", client=client
        )

        subscribed = Entitlement.objects.get_subscribed(user)
        assert entitlement in subscribed
        assert unrelated_entitlement not in subscribed

    @pytest.mark.django_db
    def test_get_subscribed_anonymous(self):
        """Anonymous users get empty queryset"""

        anonymous = AnonymousUser()
        owner = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=owner, client_id="client-subscribed-anon"
        )
        Entitlement.objects.create(
            name="Feature", slug="feature-subscribed-anon", client=client
        )

        subscribed = Entitlement.objects.get_subscribed(anonymous)
        assert subscribed.count() == 0

    @pytest.mark.django_db
    def test_get_owned_authenticated(self):
        """Authenticated users can view entitlements they own via client"""

        user = UserFactory()
        other_user = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=user, client_id="client-owned1"
        )
        other_client = Client.objects.create(
            name="Other Client", owner=other_user, client_id="client-owned2"
        )

        owned_entitlement = Entitlement.objects.create(
            name="Owned Feature", slug="owned-feature-auth", client=client
        )
        unowned_entitlement = Entitlement.objects.create(
            name="Unowned Feature", slug="unowned-feature-auth", client=other_client
        )

        owned = Entitlement.objects.get_owned(user)
        assert owned_entitlement in owned
        assert unowned_entitlement not in owned

    @pytest.mark.django_db
    def test_get_owned_anonymous(self):
        """Anonymous users get empty queryset"""

        anonymous = AnonymousUser()
        owner = UserFactory()
        client = Client.objects.create(
            name="Test Client", owner=owner, client_id="client-owned-anon"
        )
        Entitlement.objects.create(
            name="Feature", slug="feature-owned-anon", client=client
        )

        owned = Entitlement.objects.get_owned(anonymous)
        assert owned.count() == 0


class TestInvoiceQuerySet(TestCase):
    """Unit tests for Invoice queryset"""

    @pytest.mark.django_db
    def test_overdue_empty_when_no_invoices(self):
        """Overdue returns empty queryset when no invoices exist"""
        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 0

    @pytest.mark.django_db
    def test_overdue_finds_past_due_invoices(self):
        """Verify overdue finds invoices past their due date"""
        # Create invoice that's 35 days overdue
        old_due_date = timezone.now().date() - timedelta(days=35)
        InvoiceFactory(status="open", due_date=old_due_date)

        # Create invoice that's overdue within grace period
        recent_due_date = timezone.now().date() - timedelta(days=10)
        InvoiceFactory(status="open", due_date=recent_due_date)

        # Query with 30-day grace period
        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_excludes_paid_invoices(self):
        """Test overdue excludes paid invoices even if past due date"""
        old_due_date = timezone.now().date() - timedelta(days=35)

        # Create overdue but paid invoice
        InvoiceFactory(status="paid", due_date=old_due_date)

        # Create overdue open invoice
        InvoiceFactory(status="open", due_date=old_due_date)

        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_excludes_other_statuses(self):
        """Test overdue only includes open status invoices"""
        old_due_date = timezone.now().date() - timedelta(days=35)

        # Create invoices with various statuses
        InvoiceFactory(status="open", due_date=old_due_date)
        InvoiceFactory(status="void", due_date=old_due_date)
        InvoiceFactory(status="uncollectible", due_date=old_due_date)
        InvoiceFactory(status="draft", due_date=old_due_date)

        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_respects_grace_period(self):
        """Test overdue respects the grace period parameter"""
        # Create invoices at different overdue levels
        InvoiceFactory.create_batch(
            3,
            status="open",
            due_date=timezone.now().date() - timedelta(days=70),
        )
        InvoiceFactory.create_batch(
            2,
            status="open",
            due_date=timezone.now().date() - timedelta(days=45),
        )
        InvoiceFactory.create_batch(
            4,
            status="open",
            due_date=timezone.now().date() - timedelta(days=20),
        )

        # 30-day grace period should find 5 invoices (70 and 45 days old)
        assert Invoice.objects.overdue(grace_period_days=30).count() == 5

        # 60-day grace period should find 3 invoices (only 70 days old)
        assert Invoice.objects.overdue(grace_period_days=60).count() == 3

        # 15-day grace period should find all 9 invoices
        assert Invoice.objects.overdue(grace_period_days=15).count() == 9
