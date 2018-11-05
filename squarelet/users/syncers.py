"""
Sync user information to client sites
"""

# Django
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist

# Local
from ..syncers import syncers
from ..users.models import User


class MuckRockSyncSiteUser(syncers.MuckRockSyncSite):

    create_path = "/user/"
    update_path = "/user/{obj.pk}/"

    def _get_data(self, obj, create=False):
        """Get the user data"""
        data = {
            "profile": {"full_name": obj.name, "avatar_url": obj.avatar_url},
            "username": obj.username,
        }
        if create:
            data["profile"]["uuid"] = str(obj.pk)
        try:
            email = obj.emailaddress_set.get(primary=True)
        except (ObjectDoesNotExist, MultipleObjectsReturned):
            data["email"] = obj.email
        else:
            data["email"] = email.email
            data["profile"]["email_confirmed"] = email.verified
        return data


class UserSyncer(syncers.Syncer):
    model = User
    sites = {"muckrock": MuckRockSyncSiteUser()}


syncers.register(User, UserSyncer)
