# Django
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView

# Squarelet
from squarelet.organizations.choices import RelationshipType
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
        context["pending_invitations"] = OrganizationInvitation.objects.filter(
            from_organization__slug=org.slug,
            accepted_at__isnull=True,
            rejected_at__isnull=True,
            withdrawn_at__isnull=True,
        ).select_related("to_organization")

        return context

    def post(self, request, *args, **kwargs):
        self.organization = self.get_object()

        if not self.request.user.is_authenticated:
            return redirect(self.organization)

        action = request.POST.get("action")

        if action == "send_invite":
            self._handle_send_invite(request)
        elif action == "resend_invite":
            self._handle_resend_invite(request)
        elif action == "withdraw_invite":
            self._handle_withdraw_invite(request)

        return redirect("organizations:manage-member-orgs", slug=self.organization.slug)

    def _get_invitation(self, request):
        invitation_uuid = request.POST.get("invitation")

        try:
            invitation = OrganizationInvitation.objects.get(
                uuid=invitation_uuid, from_organization=self.organization
            )
        except OrganizationInvitation.DoesNotExist:
            messages.error(request, _("Invitation not found"))
            return None

        return invitation

    def _handle_send_invite(self, request):
        to_org_id = request.POST.get("to_organization")

        try:
            to_org = Organization.objects.get(id=to_org_id, individual=False)
        except Organization.DoesNotExist:
            messages.error(request, _("Organization not found"))
            return

        if self.organization.has_member_org(to_org) or self.organization == to_org:
            messages.info(
                request,
                _(f"{to_org.name} is already a member of this organization."),
            )
            return

        invitation = OrganizationInvitation.objects.create(
            from_user=self.request.user,
            from_organization=self.organization,
            to_organization=to_org,
            relationship_type=RelationshipType.member,
        )

        invitation.send()

        messages.success(request, _("Invitation sent"))

    def _handle_resend_invite(self, request):
        invitation = self._get_invitation(request)

        if not invitation or not invitation.is_pending:
            return

        invitation.send()

        messages.info(request, _("Invitation resent"))

    def _handle_withdraw_invite(self, request):
        invitation = self._get_invitation(request)

        if not invitation:
            return

        invitation.withdraw()

        messages.info(request, _("Invitation withdrawn"))


class AcceptMemberOrgInvitation(PermissionRequiredMixin, DetailView):
    queryset = OrganizationInvitation.objects.pending()
    slug_field = "uuid"
    slug_url_kwarg = "uuid"
    template_name = "organizations/group_invitation_detail.html"

    def has_permission(self):
        invitation = self.get_object()
        org = invitation.to_organization
        return org.has_admin(self.request.user)
