# Django
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Organization, Plan

# Local
from .. import views

# pylint: disable=invalid-name,unused-argument


@pytest.mark.django_db()
class TestCanManageMembersRule:
    """Test the organizations.can_manage_members rule-based permission"""

    def test_admin_has_can_manage_members(self, organization_factory, user_factory):
        """Org admins get can_manage_members dynamically via django-rules"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.can_manage_members", org)

    def test_member_lacks_can_manage_members(self, organization_factory, user_factory):
        """Regular members do not get can_manage_members"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert not member.has_perm("organizations.can_manage_members", org)

    def test_anonymous_lacks_can_manage_members(self, organization_factory):
        """Anonymous users do not get can_manage_members"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.can_manage_members", org)

    def test_staff_without_perm_lacks_can_manage_members(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_manage_members"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_manage_members", org)

    def test_staff_with_db_perm_has_can_manage_members(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_manage_members", content_type=ct)
        user.user_permissions.add(perm)
        # Refresh user to clear cached permissions
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_manage_members")


@pytest.mark.django_db()
class TestManageMembersViewPermission(ViewTestMixin):
    """Test that ManageMembers view uses the permission mixin"""

    view = views.ManageMembers
    url = "/organizations/{slug}/manage-members/"

    def test_manage_members_view_accessible_by_admin(
        self, rf, organization_factory, user_factory
    ):
        """Admin can access ManageMembers"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        response = self.call_view(rf, admin, slug=org.slug)
        assert response.status_code == 200

    def test_manage_members_view_denied_for_member(
        self, rf, organization_factory, user_factory
    ):
        """Regular member gets PermissionDenied"""
        member = user_factory()
        org = organization_factory(users=[member])
        with pytest.raises(PermissionDenied):
            self.call_view(rf, member, slug=org.slug)

    def test_manage_members_view_denied_for_staff_without_perm(
        self, rf, organization_factory, user_factory
    ):
        """Staff without the permission gets PermissionDenied"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        with pytest.raises(PermissionDenied):
            self.call_view(rf, staff, slug=org.slug)

    def test_manage_members_view_accessible_by_staff_with_db_perm(
        self, rf, organization_factory, user_factory
    ):
        """Staff with DB-assigned permission can access ManageMembers"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_manage_members", content_type=ct)
        staff.user_permissions.add(perm)
        staff = type(staff).objects.get(pk=staff.pk)
        response = self.call_view(rf, staff, slug=org.slug)
        assert response.status_code == 200

    def test_manage_members_view_denied_for_anonymous(
        self, rf, organization_factory, user_factory
    ):
        """Anonymous user gets redirected (302) to login"""
        org = organization_factory()
        response = self.call_view(rf, slug=org.slug)
        assert response.status_code == 302


@pytest.mark.django_db()
class TestDetailPermissionContext(ViewTestMixin):
    """Test that has_perm evaluates correctly for detail page scenarios.

    The template uses {% has_perm "organizations.can_manage_members" user org %}
    to decide whether to show the Manage Members link. These tests verify
    the permission evaluation that drives that template logic.
    """

    view = views.Detail
    url = "/organizations/{slug}/"

    def test_detail_admin_sees_manage_members_link(
        self, rf, organization_factory, user_factory
    ):
        """Admin has can_manage_members on the org (template shows link)"""
        Plan.objects.get_or_create(
            slug="organization", defaults={"name": "Organization"}
        )
        admin = user_factory()
        org = organization_factory(admins=[admin])
        # Verify the permission the template checks
        assert admin.has_perm("organizations.can_manage_members", org)
        # Verify context has is_admin for backwards compat
        response = self.call_view(rf, admin, slug=org.slug)
        assert response.context_data["is_admin"]

    def test_detail_member_lacks_manage_members_link(
        self, rf, organization_factory, user_factory
    ):
        """Regular member does NOT have can_manage_members (template hides link)"""
        Plan.objects.get_or_create(
            slug="organization", defaults={"name": "Organization"}
        )
        member = user_factory()
        org = organization_factory(users=[member])
        assert not member.has_perm("organizations.can_manage_members", org)
        response = self.call_view(rf, member, slug=org.slug)
        assert not response.context_data["is_admin"]

    def test_detail_staff_without_perm_lacks_manage_members(
        self, rf, organization_factory, user_factory
    ):
        """Staff without the permission does NOT have can_manage_members on the org"""
        Plan.objects.get_or_create(
            slug="organization", defaults={"name": "Organization"}
        )
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_manage_members", org)

    def test_detail_perm_assigned_user_sees_manage_members_link(
        self, organization_factory, user_factory
    ):
        """User with DB-assigned can_manage_members gets the perm (template shows link)

        DB-assigned perms work globally (without object). The mixin and template
        both check global perms as a fallback when object-level check fails.
        """
        user = user_factory()
        organization_factory(users=[user])
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_manage_members", content_type=ct)
        user.user_permissions.add(perm)
        # Refresh user to clear cached permissions
        user = type(user).objects.get(pk=user.pk)
        # DB-assigned perm works without object (global)
        assert user.has_perm("organizations.can_manage_members")


@pytest.mark.django_db()
class TestCanViewMembersRule:
    """Test the organizations.can_view_members rule-based permission"""

    def test_member_has_can_view_members(self, organization_factory, user_factory):
        """Org members get can_view_members dynamically via django-rules"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert member.has_perm("organizations.can_view_members", org)

    def test_admin_has_can_view_members(self, organization_factory, user_factory):
        """Org admins also get can_view_members (admins are members)"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.can_view_members", org)

    def test_non_member_lacks_can_view_members(
        self, organization_factory, user_factory
    ):
        """Non-members do not get can_view_members"""
        user = user_factory()
        org = organization_factory()
        assert not user.has_perm("organizations.can_view_members", org)

    def test_anonymous_lacks_can_view_members(self, organization_factory):
        """Anonymous users do not get can_view_members"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.can_view_members", org)

    def test_staff_without_perm_lacks_can_view_members(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_view_members"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_view_members", org)

    def test_staff_with_db_perm_has_can_view_members(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_view_members", content_type=ct)
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_view_members")


@pytest.mark.django_db()
class TestChangeOrganizationRule:
    """Test the organizations.change_organization rule-based permission"""

    def test_admin_has_change_organization(self, organization_factory, user_factory):
        """Org admins get change_organization dynamically via django-rules"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.change_organization", org)

    def test_member_lacks_change_organization(self, organization_factory, user_factory):
        """Regular members do not get change_organization"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert not member.has_perm("organizations.change_organization", org)

    def test_anonymous_lacks_change_organization(self, organization_factory):
        """Anonymous users do not get change_organization"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.change_organization", org)

    def test_staff_without_perm_lacks_change_organization(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant change_organization on an object"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.change_organization", org)

    def test_staff_with_db_perm_has_change_organization(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="change_organization", content_type=ct)
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.change_organization")


@pytest.mark.django_db()
class TestCanReviewProfileChangesRule:
    """Test the organizations.can_review_profile_changes permission.

    This permission has no django-rules registration — it only works via
    DB assignment (user_permissions/groups).
    """

    def test_no_rule_registered(self, organization_factory, user_factory):
        """Without a rule, object-level check returns False for everyone"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert not admin.has_perm("organizations.can_review_profile_changes", org)

    def test_staff_without_db_perm_lacks_review(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_review_profile_changes"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_review_profile_changes", org)
        assert not staff.has_perm("organizations.can_review_profile_changes")

    def test_user_with_db_perm_has_review(self, user_factory):
        """A user with the DB-assigned permission gets it"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(
            codename="can_review_profile_changes", content_type=ct
        )
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_review_profile_changes")


@pytest.mark.django_db()
class TestCanViewSubscriptionRule:
    """Test the organizations.can_view_subscription rule-based permission"""

    def test_member_has_can_view_subscription(self, organization_factory, user_factory):
        """Org members get can_view_subscription dynamically via django-rules"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert member.has_perm("organizations.can_view_subscription", org)

    def test_admin_has_can_view_subscription(self, organization_factory, user_factory):
        """Org admins also get can_view_subscription (admins are members)"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.can_view_subscription", org)

    def test_non_member_lacks_can_view_subscription(
        self, organization_factory, user_factory
    ):
        """Non-members do not get can_view_subscription"""
        user = user_factory()
        org = organization_factory()
        assert not user.has_perm("organizations.can_view_subscription", org)

    def test_anonymous_lacks_can_view_subscription(self, organization_factory):
        """Anonymous users do not get can_view_subscription"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.can_view_subscription", org)

    def test_staff_without_perm_lacks_can_view_subscription(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_view_subscription"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_view_subscription", org)

    def test_staff_with_db_perm_has_can_view_subscription(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_view_subscription", content_type=ct)
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_view_subscription")


@pytest.mark.django_db()
class TestCanEditSubscriptionRule:
    """Test the organizations.can_edit_subscription rule-based permission"""

    def test_admin_has_can_edit_subscription(self, organization_factory, user_factory):
        """Org admins get can_edit_subscription dynamically via django-rules"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.can_edit_subscription", org)

    def test_member_lacks_can_edit_subscription(
        self, organization_factory, user_factory
    ):
        """Regular members do not get can_edit_subscription"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert not member.has_perm("organizations.can_edit_subscription", org)

    def test_anonymous_lacks_can_edit_subscription(self, organization_factory):
        """Anonymous users do not get can_edit_subscription"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.can_edit_subscription", org)

    def test_staff_without_perm_lacks_can_edit_subscription(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_edit_subscription"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_edit_subscription", org)

    def test_staff_with_db_perm_has_can_edit_subscription(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_edit_subscription", content_type=ct)
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_edit_subscription")


@pytest.mark.django_db()
class TestCanViewChargeDetailRule:
    """Test the organizations.can_view_charge rule-based permission"""

    def test_admin_has_can_view_charge(self, organization_factory, user_factory):
        """Org admins get can_view_charge dynamically via django-rules"""
        admin = user_factory()
        org = organization_factory(admins=[admin])
        assert admin.has_perm("organizations.can_view_charge", org)

    def test_member_lacks_can_view_charge(
        self, organization_factory, user_factory
    ):
        """Regular members do not get can_view_charge"""
        member = user_factory()
        org = organization_factory(users=[member])
        assert not member.has_perm("organizations.can_view_charge", org)

    def test_anonymous_lacks_can_view_charge(self, organization_factory):
        """Anonymous users do not get can_view_charge"""
        org = organization_factory()
        anon = AnonymousUser()
        assert not anon.has_perm("organizations.can_view_charge", org)

    def test_staff_without_perm_lacks_can_view_charge(
        self, organization_factory, user_factory
    ):
        """Staff status alone does NOT grant can_view_charge"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        assert not staff.has_perm("organizations.can_view_charge", org)

    def test_staff_with_db_perm_has_can_view_charge(self, user_factory):
        """A user with the DB-assigned permission gets it (via ModelBackend)"""
        user = user_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(
            codename="can_view_charge", content_type=ct
        )
        user.user_permissions.add(perm)
        user = type(user).objects.get(pk=user.pk)
        assert user.has_perm("organizations.can_view_charge")


@pytest.mark.django_db()
class TestUpdateSubscriptionViewPermission(ViewTestMixin):
    """Test that UpdateSubscription view uses OrganizationPermissionMixin"""

    view = views.UpdateSubscription
    url = "/organizations/{slug}/payment/"

    def test_accessible_by_admin(self, rf, organization_factory, user_factory, mocker):
        """Admin can access UpdateSubscription"""
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        admin = user_factory()
        org = organization_factory(admins=[admin])
        response = self.call_view(rf, admin, slug=org.slug)
        assert response.status_code == 200

    def test_denied_for_member(self, rf, organization_factory, user_factory):
        """Regular member gets PermissionDenied"""
        member = user_factory()
        org = organization_factory(users=[member])
        with pytest.raises(PermissionDenied):
            self.call_view(rf, member, slug=org.slug)

    def test_denied_for_staff_without_perm(
        self, rf, organization_factory, user_factory
    ):
        """Staff without the permission gets PermissionDenied"""
        staff = user_factory(is_staff=True)
        org = organization_factory()
        with pytest.raises(PermissionDenied):
            self.call_view(rf, staff, slug=org.slug)

    def test_accessible_by_staff_with_db_perm(
        self, rf, organization_factory, user_factory, mocker
    ):
        """Staff with DB-assigned permission can access UpdateSubscription"""
        mocker.patch("squarelet.organizations.models.Customer.card", None)
        staff = user_factory(is_staff=True)
        org = organization_factory()
        ct = ContentType.objects.get_for_model(Organization)
        perm = Permission.objects.get(codename="can_edit_subscription", content_type=ct)
        staff.user_permissions.add(perm)
        staff = type(staff).objects.get(pk=staff.pk)
        response = self.call_view(rf, staff, slug=org.slug)
        assert response.status_code == 200

    def test_denied_for_anonymous(self, rf, organization_factory):
        """Anonymous user gets redirected (302) to login"""
        org = organization_factory()
        response = self.call_view(rf, slug=org.slug)
        assert response.status_code == 302
