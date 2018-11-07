# Django
from django.contrib.auth.mixins import UserPassesTestMixin


class OrganizationAdminMixin(UserPassesTestMixin):
    """Only allow access to organization admins"""

    def test_func(self):
        return self.get_object().has_admin(self.request.user)
