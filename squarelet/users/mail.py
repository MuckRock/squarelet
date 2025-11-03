# Django
from django.conf import settings
from django.contrib.auth.models import Group

# Standard Library
from datetime import date

# Third Party
from allauth.mfa.utils import is_mfa_enabled

# Squarelet
from squarelet.core.mail import Email
from squarelet.users.models import User


class PermissionsDigest(Email):
    """A digest that provides an overview of who has what permissions"""

    template = "users/email/permissions.html"

    def __init__(self, **kwargs):
        kwargs["subject"] = f"{date.today()} Accounts Permissions Digest"
        kwargs["to"] = settings.PERMISSIONS_DIGEST_EMAILS
        kwargs["extra_context"] = self.get_context()
        super().__init__(**kwargs)

    def get_context(self):
        staff = User.objects.filter(is_staff=True)
        staff = [(u, is_mfa_enabled(u)) for u in staff]
        return {
            "superusers": User.objects.filter(is_superuser=True),
            "staff": staff,
            "groups": Group.objects.prefetch_related("user_set"),
            "user_permissions": User.user_permissions.through.objects.select_related(
                "user",
                "permission",
            ),
        }
