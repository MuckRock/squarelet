# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

# Third Party
import pytest
from oidc_provider.models import Client

# Squarelet
from squarelet.organizations.models import Entitlement
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    PlanFactory,
    SubscriptionItemFactory,
)
from squarelet.users.tests.factories import UserFactory


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
        SubscriptionItemFactory(subscription__organization=org, plan=plan)

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
