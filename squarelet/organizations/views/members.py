# Django
from django.conf import settings
from django.contrib import messages
from django.http.response import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.views.generic import DetailView

# Squarelet
from squarelet.core.utils import get_redirect_url, new_action, pluralize
from squarelet.organizations.forms import AddMemberForm
from squarelet.organizations.mixins import OrganizationAdminMixin
from squarelet.organizations.models import Invitation, Membership, Organization


class ManageMembers(OrganizationAdminMixin, DetailView):
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
            messages.error(
                request, addmember_form.errors.get("emails", ["Invalid input."])[0]
            )
        else:
            emails = addmember_form.cleaned_data["emails"]
            invitations_sent = 0
            invited_emails = []
            for email in emails:
                is_already_member = self.organization.has_member_by_email(email)
                existing_open_invite = self.organization.get_existing_open_invite(email)
                if is_already_member:
                    messages.info(
                        self.request,
                        f"{email} is already a member of this organization.",
                    )
                    continue

                if existing_open_invite:
                    existing_open_invite.send()
                    messages.success(
                        self.request,
                        f"Resent invitation to {email}.",
                    )
                    continue

                invitation = Invitation.objects.create(
                    organization=self.organization,
                    email=email,
                )
                invitation.send()
                invitations_sent += 1
                invited_emails.append(email)

            # Log staff action to activity stream (once for the batch)
            if invitations_sent > 0 and request.user.is_staff:
                # Include up to 10 email addresses in the description
                if len(invited_emails) <= 10:
                    email_list = ", ".join(invited_emails)
                else:
                    email_list = (
                        ", ".join(invited_emails[:10])
                        + f" and {len(invited_emails) - 10} more"
                    )
                new_action(
                    actor=request.user,
                    verb="sent organization invitation",
                    target=self.organization,
                    description=email_list,
                )

            messages.success(
                self.request,
                f"{invitations_sent} {pluralize(invitations_sent, 'invitation')} sent",
            )

        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_add_member_link(self, request):
        # Create an invitation and display it to the admin
        invitation = Invitation.objects.create(
            organization=self.organization,
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
            invite.reject()

            # Log staff action to activity stream
            if request.user.is_staff:
                new_action(
                    actor=request.user,
                    verb="revoked organization invitation",
                    action_object=invite,
                    target=self.organization,
                    description=invite.email if invite.email else None,
                )

        return self._handle_invite(
            request,
            handle_revoke,
            lambda invite: f"Invitation to {invite.email} revoked",
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
        """Accept the invitation"""
        if not request.user.is_authenticated:
            return HttpResponseBadRequest()
        invitation = self.get_object()
        action = request.POST.get("action")
        if action == "accept":
            invitation.accept(request.user)
            messages.success(request, "Invitation accepted")
            return get_redirect_url(request, redirect(invitation.organization))
        elif action == "reject":
            # Associate the user with the invitation for auditing purposes
            if invitation.user is None:
                invitation.user = request.user
                invitation.save()
            invitation.reject()
            if invitation.request:
                messages.info(request, "Invitation withdrawn")
            else:
                messages.info(request, "Invitation rejected")
            return get_redirect_url(request, redirect(request.user))
        else:
            messages.error(request, "Invalid choice")
            return get_redirect_url(request, redirect(request.user))
