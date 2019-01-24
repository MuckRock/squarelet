# Django
from django.contrib.auth.mixins import UserPassesTestMixin


class OrganizationAdminMixin(UserPassesTestMixin):
    """Only allow access to organization admins"""

    def test_func(self):
        return self.get_object().has_admin(self.request.user)


class IndividualMixin(object):
    """Adapt a organizational view for a user's individual organization"""

    def get_object(self, queryset=None):
        # pylint: disable=unused-argument
        return self.request.user.individual_organization
