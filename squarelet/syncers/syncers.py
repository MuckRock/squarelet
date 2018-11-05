
# Django
from django.conf import settings

# Standard Library
import logging

# Third Party
import requests

logger = logging.getLogger(__name__)

# this is the global registry of syncers
syncers = {}


def register(model, syncer):
    syncers[model.__name__] = syncer


class Syncer:
    """A class to configure syncing a model to all client sites"""

    sites = {}

    def __init__(self, site_name, *args):
        # pylint: disable=no-value-for-parameter
        if not hasattr(self, "sites"):
            raise NotImplementedError(
                "subclasses of Syncer must provide a sites attribute"
            )
        self.site = self.sites[site_name]
        self.obj = self.get_object(*args)

    def get_object(self, obj_pk, *args):
        """Fetch the model to be synced"""
        # pylint: disable=unused-argument
        if not hasattr(self, "model"):
            raise NotImplementedError(
                "subclasses of Syncer must provide a model attribute or a get_object "
                "method"
            )
        return self.model.objects.get(pk=obj_pk)

    def action(self, action):
        """Call the appropriate action from the individual site's syncer"""
        return getattr(self.site, action)(self.obj)


class SyncSite:
    """Syncer for a single client site"""

    def create(self, obj):
        """Create an object"""
        data = self._get_data(obj, create=True)
        return self._api_call("post", self.create_path.format(obj=obj), data)

    def update(self, obj):
        """Update an object"""
        data = self._get_data(obj)
        return self._api_call("patch", self.update_path.format(obj=obj), data)

    def delete(self, obj):
        """Delete an object"""
        return self._api_call("delete", self.delete_path.format(obj=obj))

    def _get_data(self, obj, create=False):
        """Get the data needed to create or update an object"""
        # pylint: disable=unused-argument
        return {}

    def _api_call(self, method, path, data=None):
        """Call the client site's API"""
        raise NotImplementedError(
            "subclasses of SyncSite must provide an _api_call method"
        )


class MuckRockSyncSite(SyncSite):
    """Sync data to MuckRock"""

    def _api_call(self, method, path, data=None):
        """Call the MuckRock API as the squarelet admin account"""
        if data is None:
            data = {}
        url = f"{settings.MUCKROCK_URL}/api_v1{path}"
        headers = {
            "Authorization": f"Token {settings.MUCKROCK_TOKEN}",
            "content-type": "application/json",
        }
        return requests.request(method, url, json=data, headers=headers)
