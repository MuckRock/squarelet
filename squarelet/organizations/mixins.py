# Django
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin


class OrganizationAdminMixin(UserPassesTestMixin):
    """Only allow access to organization admins"""

    def test_func(self):
        is_staff = self.request.user.is_staff
        is_admin = self.request.user.is_authenticated and self.get_object().has_admin(
            self.request.user
        )
        return is_admin or is_staff


class OrganizationPermissionMixin(PermissionRequiredMixin):
    """Check a permission against the organization object.

    Works with both django-rules (dynamic) and ModelBackend (DB-assigned).
    Authenticated users without permission get 403; anonymous users are redirected.
    """

    def has_permission(self):
        user = self.request.user
        obj = self.get_object()
        perms = self.get_permission_required()
        return all(user.has_perm(perm, obj) or user.has_perm(perm) for perm in perms)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            self.raise_exception = True
        return super().handle_no_permission()


class IndividualMixin:
    """Adapt a organizational view for a user's individual organization"""

    def get_object(self, queryset=None):
        # pylint: disable=unused-argument
        if self.request.user.is_authenticated:
            return self.request.user.individual_organization
        else:
            return None


class VerifiedJournalistMixin(UserPassesTestMixin):
    """Only allow access to admins of organizations that are marked verified"""

    def test_func(self):
        # Check if the user is authenticated, an admin
        # and the organization is verified as a journalist
        organization = self.get_object()
        return (
            self.request.user.is_authenticated
            and organization.verified_journalist
            and organization.has_admin(self.request.user)
        )
