# Django
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.utils.translation import ugettext_lazy as _

# Third Party
from oidc_provider.lib.claims import ScopeClaims

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer


def userinfo(claims, user):
    claims["name"] = user.name
    claims["preferred_username"] = user.username
    claims["updated_at"] = user.updated_at
    claims["picture"] = user.avatar_url

    try:
        email = user.emailaddress_set.get(primary=True)
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        claims["email"] = ""
        claims["email_verified"] = False
    else:
        claims["email"] = email.email
        claims["email_verified"] = email.verified

    return claims


class CustomScopeClaims(ScopeClaims):
    """Custom Scope Claims for OIDC"""

    info_uuid = (_("UUID"), _("Access to the user's UUID"))
    info_organizations = (_("organizations"), _("Access to the user's organizations"))
    info_preferences = (_("preferences"), _("Access to the user's preferences"))

    def scope_uuid(self):
        """Populate the scope with the UUID"""
        return {"uuid": self.user.pk}

    def scope_organizations(self):
        """Populate the scope with the organizations"""
        return {
            "organizations": [
                MembershipSerializer(m).data
                for m in self.user.memberships.select_related("organization__plan")
            ]
        }

    def scope_preferences(self):
        """Populate the scope with user preferences"""
        return {"use_autologin": self.user.use_autologin}
