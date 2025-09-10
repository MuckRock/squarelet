# Django
from django.contrib.auth.mixins import UserPassesTestMixin


class OrganizationAdminMixin(UserPassesTestMixin):
    """Only allow access to organization admins"""

    def test_func(self):
        is_staff = self.request.user.is_staff
        is_admin = self.request.user.is_authenticated and self.get_object().has_admin(
            self.request.user
        )
        return is_admin or is_staff


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
