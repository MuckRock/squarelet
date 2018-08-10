
# Django
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.utils.translation import ugettext_lazy as _

# Third Party
from oidc_provider.lib.claims import ScopeClaims


def userinfo(claims, user):
    claims["name"] = user.name
    claims["preferred_username"] = user.username
    claims["updated_at"] = user.updated_at
    if user.avatar and user.avatar.url.startswith("http"):
        claims["picture"] = user.avatar.url
    elif user.avatar:
        claims["picture"] = f"{settings.SQUARELET_URL}{user.avatar.url}"

    try:
        email = user.emailaddress_set.get(primary=True)
        claims["email"] = email.email
        claims["email_verified"] = email.verified
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        pass

    return claims


class CustomScopeClaims(ScopeClaims):
    """Custom Scope Claims for OIDC"""

    info_uuid = (_("UUID"), _("Access to the user's UUID"))

    def scope_uuid(self):
        """Populate the scope with the UUID"""
        return {"uuid": self.user.pk}
