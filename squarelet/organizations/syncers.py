
# Squarelet
from squarelet.organizations.models import Membership, Organization
from squarelet.syncers import syncers


class MuckRockSyncSiteOrganization(syncers.MuckRockSyncSite):

    create_path = "/organization/"
    update_path = "/organization/{obj.pk}/"

    def _get_data(self, obj, create=False):
        """Get the organization data"""
        data = {
            "name": obj.name,
            "private": obj.private,
            "plan": obj.plan,
            "individual": obj.individual,
        }
        if create:
            data["uuid"] = str(obj.pk)
        return data


class OrganizationSyncer(syncers.Syncer):
    model = Organization
    sites = {"muckrock": MuckRockSyncSiteOrganization()}


class MuckRockSyncSiteMembership(syncers.MuckRockSyncSite):

    create_path = "/organization/{obj[organization_pk]}/membership/"
    delete_path = "/organization/{obj[organization_pk]}/membership/{obj[user_pk]}/"

    def _get_data(self, obj, create=False):
        """Get the organization data"""
        return {"user": str(obj["user_pk"])}


class MembershipSyncer(syncers.Syncer):
    sites = {"muckrock": MuckRockSyncSiteMembership()}

    def get_object(self, organization_pk, user_pk, *args):
        """Get the membership based off of the organization and user pimary keys"""
        # pylint: disable=arguments-differ
        return {"organization_pk": organization_pk, "user_pk": user_pk}


syncers.register(Organization, OrganizationSyncer)
syncers.register(Membership, MembershipSyncer)
