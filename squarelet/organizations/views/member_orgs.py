# Django
from django.views.generic import DetailView

# Squarelet
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Organization
from squarelet.organizations.models.invitation import OrganizationInvitation


class ManageMemberOrgs(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_member_orgs"
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managememberorgs.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.object

        context["members"] = org.members.all()
        print(context["members"])

        return context
