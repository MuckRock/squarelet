# Django
from django.conf import settings
from django.contrib import messages
from django.http.response import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.views.generic import DetailView, ListView

# Squarelet
from squarelet.core.utils import get_redirect_url, new_action, pluralize
from squarelet.organizations.choices import InvitationRole
from squarelet.organizations.forms import AddMemberForm
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Invitation, Membership, Organization
from squarelet.users.models import User


class ManageMembers(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_members"
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managemembers.html"

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        actions = {
            "addmember": self._handle_add_member,
            "addmember_link": self._handle_add_member_link,
            "revokeinvite": self._handle_revoke_invite,
            "resendinvite": self._handle_resend_invite,
            "acceptinvite": self._handle_accept_invite,
            "rejectinvite": self._handle_reject_invite,
            "makeadmin": self._handle_makeadmin_user,
            "removeuser": self._handle_remove_user,
        }
        try:
            return actions[request.POST["action"]](request)
        except KeyError:
            return self._bad_call(request)

    def _handle_add_member(self, request):
        addmember_form = AddMemberForm(request.POST)
        if not addmember_form.is_valid():
            error_msg = (
                addmember_form.errors.get("emails")
                or addmember_form.errors.get("__all__")
                or ["Invalid input."]
            )[0]
            messages.error(request, error_msg)
            return redirect("organizations:manage-members", slug=self.organization.slug)

        invitees = self._build_invitees(addmember_form)
        role = addmember_form.cleaned_data.get("role")
        role = int(role) if role else InvitationRole.member
        invited_emails = [
            email
            for user_obj, email in invitees
            if self._invite_one(user_obj, email, role)
        ]
        if invited_emails and request.user.is_staff:
            self._log_invitations(request.user, invited_emails)
        if invited_emails:
            count = len(invited_emails)
            messages.success(
                self.request,
                f"{count} {pluralize(count, 'invitation')} sent",
            )
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _build_invitees(self, form):
        """Build (user, email) pairs from the form. Free-form emails have
        user=None; selected users carry both the user and their email so the
        invitation is tied to the account, not just the address."""
        invitees = [(None, email) for email in (form.cleaned_data["emails"] or [])]
        user_ids = form.cleaned_data.get("user_ids", [])
        if user_ids:
            for user_obj in User.objects.filter(id__in=user_ids):
                invitees.append((user_obj, user_obj.email))
        return invitees

    def _invite_one(self, user_obj, email, role):
        """Send one invitation. Returns True if an invitation was sent."""
        if user_obj is not None:
            is_already_member = self.organization.has_member(user_obj)
        else:
            is_already_member = self.organization.has_member_by_email(email)
        if is_already_member:
            messages.info(
                self.request,
                f"{email} is already a member of this organization.",
            )
            return False

        existing_open_invite = self.organization.get_existing_open_invite(email)
        if existing_open_invite:
            if user_obj is not None and existing_open_invite.user is None:
                existing_open_invite.user = user_obj
                existing_open_invite.save()
            existing_open_invite.send()
            return True

        invitation = Invitation.objects.create(
            organization=self.organization,
            email=email,
            user=user_obj,
            role=role,
        )
        invitation.send()
        return True

    def _log_invitations(self, actor, invited_emails):
        """Log a staff-triggered invitation batch to the activity stream."""
        if len(invited_emails) <= 10:
            description = ", ".join(invited_emails)
        else:
            description = (
                ", ".join(invited_emails[:10]) + f" and {len(invited_emails) - 10} more"
            )
        new_action(
            actor=actor,
            verb="sent organization invitation",
            target=self.organization,
            description=description,
        )

    def _handle_add_member_link(self, request):
        # Create an invitation and display it to the admin
        invitation = Invitation.objects.create(
            organization=self.organization,
            role=InvitationRole.member,
        )
        url = reverse("organizations:invitation", args=(invitation.uuid,))
        messages.success(
            self.request,
            format_html(
                "Invitation link created:<p>{}{}</p>", settings.SQUARELET_URL, url
            ),
        )
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_invite(self, request, invite_fn, success_message_fn):
        try:
            inviteid = request.POST.get("inviteid")
            invite = Invitation.objects.get_open().get(
                pk=inviteid, organization=self.organization
            )
            invite_fn(invite)
            messages.success(self.request, success_message_fn(invite))
        except Invitation.DoesNotExist:
            return self._bad_call(request)
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_revoke_invite(self, request):
        def handle_revoke(invite):
            invite.withdraw()

            # Log staff action to activity stream
            if request.user.is_staff:
                new_action(
                    actor=request.user,
                    verb="withdrew organization invitation",
                    action_object=invite,
                    target=self.organization,
                    description=invite.email if invite.email else None,
                )

        return self._handle_invite(
            request,
            handle_revoke,
            lambda invite: f"Invitation to {invite.email} withdrawn",
        )

    def _handle_resend_invite(self, request):
        return self._handle_invite(
            request,
            lambda invite: invite.send(),
            lambda invite: f"Invitation to {invite.email} resent successfully.",
        )

    def _handle_accept_invite(self, request):
        return self._handle_invite(
            request,
            lambda invite: invite.accept(),
            lambda invite: f"Invitation from {invite.email} accepted",
        )

    def _handle_reject_invite(self, request):
        return self._handle_invite(
            request,
            lambda invite: invite.reject(),
            lambda invite: f"Invitation from {invite.email} rejected",
        )

    def _handle_user(self, request, membership_fn, success_message_fn):
        try:
            userid = request.POST.get("userid")
            membership = self.organization.memberships.get(user_id=userid)
            membership_fn(membership)
            messages.success(self.request, success_message_fn(membership))
        except Membership.DoesNotExist:
            return self._bad_call(request)
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_makeadmin_user(self, request):
        admin_param = request.POST.get("admin")
        if admin_param == "true":
            set_admin = True
        elif admin_param == "false":
            set_admin = False
        else:
            return self._bad_call(request)

        def handle_make_admin(membership):
            membership.admin = set_admin
            membership.save()

            # Log staff action to activity stream
            if request.user.is_staff:
                new_action(
                    actor=request.user,
                    verb=(
                        "promoted member to admin"
                        if set_admin
                        else "demoted admin to member"
                    ),
                    action_object=membership.user,
                    target=self.organization,
                )

        return self._handle_user(
            request,
            handle_make_admin,
            lambda membership: (
                f"{membership.user.username} promoted to admin"
                if set_admin
                else f"{membership.user.username} demoted to member"
            ),
        )

    def _handle_remove_user(self, request):
        def handle_remove(membership):
            user = membership.user
            membership.delete()

            # Log staff action to activity stream
            if request.user.is_staff:
                new_action(
                    actor=request.user,
                    verb="removed member",
                    action_object=user,
                    target=self.organization,
                )

        return self._handle_user(
            request,
            handle_remove,
            lambda membership: f"{membership.user.username} removed",
        )

    def _bad_call(self, request):
        messages.error(self.request, "An unexpected error occurred")
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user
        # Use member_users() for consistent sorting: current user, admins, then members
        users = self.object.member_users(self.request)
        context["members"] = [u.org_membership_list[0] for u in users]
        context["requested_invitations"] = list(
            self.object.invitations.get_pending_requests()
        )
        context["pending_invitations"] = list(
            self.object.invitations.get_pending_invitations()
        )
        return context


class InvitationAccept(DetailView):
    queryset = Invitation.objects.get_pending()
    slug_field = "uuid"
    slug_url_kwarg = "uuid"

    def dispatch(self, request, *args, **kwargs):
        """
        If the user is not authenticated, store the invitation in the session,
        so that the invitation can be associated on login.
        User association only happens when the user explicitly accepts or rejects.
        """
        if not request.user.is_authenticated:
            request.session["invitation"] = str(kwargs["uuid"])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Accept, reject, or withdraw the invitation"""
        if not request.user.is_authenticated:
            return HttpResponseBadRequest()
        invitation = self.get_object()
        handlers = {
            "accept": self._accept,
            "reject": self._reject,
            "withdraw": self._withdraw,
        }
        handler = handlers.get(request.POST.get("action"))
        if handler is None:
            messages.error(request, "Invalid choice")
            return get_redirect_url(request, redirect(request.user))
        # Drop a self-referer so get_redirect_url doesn't loop back here
        if request.META.get("HTTP_REFERER") == request.build_absolute_uri():
            del request.META["HTTP_REFERER"]
        return handler(request, invitation)

    def _accept(self, request, invitation):
        invitation.accept(request.user)
        messages.success(request, "Invitation accepted")
        return get_redirect_url(request, redirect(invitation.organization))

    def _reject(self, request, invitation):
        self._associate_user(invitation, request.user)
        invitation.reject()
        messages.info(request, "Invitation rejected")
        return get_redirect_url(request, redirect(request.user))

    def _withdraw(self, request, invitation):
        self._associate_user(invitation, request.user)
        invitation.withdraw()
        messages.info(request, "Invitation withdrawn")
        return get_redirect_url(request, redirect(request.user))

    @staticmethod
    def _associate_user(invitation, user):
        """Attach the acting user to the invitation for auditing."""
        if invitation.user is None:
            invitation.user = user
            invitation.save()


class BaseOrgInvitationRequestView(OrganizationPermissionMixin, ListView):
    """Base view for displaying invitation and request history for an organization"""

    permission_required = "organizations.can_manage_members"
    model = Invitation
    paginate_by = 20
    is_request_view = None

    def get_object(self):
        if not hasattr(self, "_organization"):
            self._organization = Organization.objects.filter(individual=False).get(
                slug=self.kwargs["slug"]
            )
        return self._organization

    def get_queryset(self):
        org = self.get_object()
        if self.is_request_view:
            return Invitation.objects.get_org_requests(org)
        return Invitation.objects.get_org_invitations(org)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.get_object()
        return context


class OrgInvitationsView(BaseOrgInvitationRequestView):
    """View to display all invitations sent by an organization"""

    template_name = "organizations/organization_invitations.html"
    context_object_name = "invitations"
    is_request_view = False


class OrgRequestsView(BaseOrgInvitationRequestView):
    """View to display all requests received by an organization"""

    template_name = "organizations/organization_requests.html"
    context_object_name = "requests"
    is_request_view = True
