# Django
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

# Third Party
from oidc_provider.lib.claims import ScopeClaims

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer


def userinfo(claims, user):
    claims["name"] = user.name
    claims["preferred_username"] = user.username
    claims["updated_at"] = user.updated_at
    claims["picture"] = user.avatar_url
    claims["bio"] = user.bio

    try:
        # TODO: Replace with user.email or user.primary_email
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
    info_bio = (_("bio"), _("Access to the user's bio"))

    def scope_uuid(self):
        """Populate the scope with the UUID"""
        return {"uuid": self.user.uuid}

    def scope_organizations(self):
        """Populate the scope with the organizations"""
        return {
            "organizations": [
                MembershipSerializer(m, context={"client": self.client}).data
                for m in self.user.memberships.all()
            ]
        }

    def scope_preferences(self):
        """Populate the scope with user preferences"""
        return {"use_autologin": self.user.use_autologin}

    def scope_bio(self):
        """Populate the scropt with the user's bio"""
        return {"bio": self.user.bio}
