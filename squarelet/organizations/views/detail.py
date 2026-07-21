# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Value as V
from django.db.models.functions import Lower, StrIndex
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView

# Standard Library
import logging
from datetime import datetime

# Squarelet
from squarelet.core.mixins import AdminLinkMixin
from squarelet.core.utils import get_redirect_url, is_rate_limited, new_action
from squarelet.organizations.forms import InvitationAcceptForm
from squarelet.organizations.models import Invitation, Membership, Organization, Plan
from squarelet.organizations.models.invitation import OrganizationInvitation
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.tasks import sync_wix

# How much to paginate organizations list by
ORG_PAGINATION = 100

logger = logging.getLogger(__name__)


class Detail(AdminLinkMixin, DetailView):
    def get_queryset(self):
        return Organization.objects.filter(individual=False).get_viewable(
            self.request.user
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.object
        user = self.request.user
        if user.is_authenticated:
            context.update(self._get_membership_context(user, org))

        users = org.member_users(self.request)
        admins = [
            u for u in users if u.org_membership_list and u.org_membership_list[0].admin
        ]
        if user.has_perm("organizations.can_view_members", org):
            context["users"] = users
        else:
            context["users"] = admins
        context["admins"] = admins

        # Get the current plan and subscription, if any
        current_plan = None
        upgrade_plan = Plan.objects.get(slug="organization")
        subscription = None
        if hasattr(org, "subscriptions"):
            subscription = org.subscriptions.first()
            if subscription and hasattr(subscription, "plan"):
                current_plan = subscription.plan
                upgrade_plan = None
        context["current_plan"] = current_plan
        context["upgrade_plan"] = upgrade_plan
        context["member_count"] = len(users)
        context["admin_count"] = len(admins)

        if current_plan and subscription:
            context.update(self._get_subscription_context(org, subscription))

        # Any member (not just admins) may request verification, but only if
        # they have confirmed an email address on their account.
        context["show_verification_request"] = (
            user.is_authenticated
            and org.has_member(user)
            and not org.verified_journalist
        )
        context["has_verified_email"] = (
            user.is_authenticated and user.has_verified_email()
        )

        if user.has_perm("organizations.can_manage_domains", org):
            context["security_settings"] = {
                "allow_auto_join": org.allow_auto_join,
                "has_email_domains": org.domains.exists(),
            }

        context["show_wix_sync"] = bool(
            org.subscriptions.filter(plan__wix=True).exists()
            or org.get_wix_plans_from_groups()
        )
        context["inherited_plans"] = org.get_inherited_plans()

        context.update(self._get_groups_context(user, org))

        return context

    def _get_membership_context(self, user, org):
        """Return context dict for the authenticated user's relationship to org."""
        is_member = org.has_member(user)
        ctx = {
            "is_admin": org.has_admin(user),
            "is_member": is_member,
            "requested_invite": user.invitations.filter(
                organization=org
            ).get_pending_requests(),
            "rejected_invite": user.invitations.filter(
                organization=org
            ).get_rejected_requests(),
            "can_auto_join": user.can_auto_join(org) and not is_member,
        }
        if user.has_perm("organizations.can_manage_members", org):
            ctx["pending_requests"] = org.invitations.get_pending_requests()
            ctx["pending_invitations"] = org.invitations.get_pending_invitations()
        return ctx

    def _get_subscription_context(self, org, subscription):
        """Return context dict for card, next charge date, and cancellation status."""
        customer = org.customer()
        ctx = {
            "current_plan_card": bool(customer.stripe_payment_method_id),
            "current_plan_card_brand": customer.payment_brand,
            "current_plan_card_last4": customer.payment_last4,
            "current_plan_cancelled": subscription.cancelled,
        }

        stripe_sub = subscription.stripe_subscription
        if stripe_sub:
            time_stamp = (
                get_payment_provider()
                .get_subscription_service()
                .get_current_period_end(stripe_sub)
            )
            if time_stamp:
                tz_datetime = datetime.fromtimestamp(
                    time_stamp, tz=timezone.get_current_timezone()
                )
                ctx["current_plan_next_charge_date"] = tz_datetime.date()

        return ctx

    def _get_groups_context(self, user, org):
        can_manage_member_orgs = user.has_perm(
            "organizations.can_manage_member_orgs", org
        )
        can_manage_groups = user.has_perm("organizations.can_manage_groups", org)
        is_member = org.has_member(user)

        ctx = {
            "groups": org.groups.all(),
            "members": org.members.all(),
        }

        if can_manage_groups:
            ctx["group_invitations"] = (
                OrganizationInvitation.objects.pending()
                .filter(to_organization=org)
                .select_related("from_organization")
            )

        ctx["show_groups_section"] = can_manage_groups and (
            len(ctx["groups"]) > 0 or len(ctx["group_invitations"]) > 0
        )

        # For collective groups, the members section is always visible to admins,
        # and visible to non-admins only when the group has member organizations.
        ctx["show_members_section"] = org.collective_enabled and (
            can_manage_member_orgs or (is_member and len(ctx["members"]) > 0)
        )

        return ctx

    def handle_join(self, request):
        user = request.user

        # Already a member
        if self.organization.has_member(user):
            return

        # Auto join if allowed
        if user.can_auto_join(self.organization):
            # Auto-join the user to the organization (no invitation needed)
            Membership.objects.create(organization=self.organization, user=user)
            messages.success(
                request, _("You have successfully joined the organization!")
            )
            return

        if is_rate_limited(
            user=user,
            count_fn=lambda user, window_start: Invitation.objects.filter(
                user=user, request=True, created_at__gte=window_start
            ).count(),
            limit=settings.ORG_JOIN_REQUEST_LIMIT,
            window_seconds=settings.ORG_JOIN_REQUEST_WINDOW,
            zendesk_subject="User reached join-request rate limit",
            zendesk_description=(
                "The following user has reached the "
                "rate-limit for joining organizations, "
                f"sending {settings.ORG_JOIN_REQUEST_LIMIT} requests in the last "
                f"{int(settings.ORG_JOIN_REQUEST_WINDOW / 3600)} hours\n\n"
                f"{settings.SQUARELET_URL}" + f"{user.get_absolute_url()}\n\n"
                "This is a signal that the user may be "
                "using their account in an inappropriate way."
            ),
        ):
            messages.error(
                request,
                format_html(
                    _(
                        "You have reached the limit of {limit} "
                        "join requests in the last {window} minutes. "
                        "Please try again later.<br><br>"
                        "<strong>Remember:</strong> Join requests "
                        "should only be used when you work "
                        "with or within an organization. "
                        "To simply contact an organization, "
                        "please reach out to admins directly."
                    ),
                    limit=settings.ORG_JOIN_REQUEST_LIMIT,
                    window=settings.ORG_JOIN_REQUEST_WINDOW // 60,
                ),
            )
            return

        # Create join request, assuming they aren't rate limited.
        # Lock the user row for the duration of the transaction so that
        # concurrent join submissions (e.g. a double-clicked button) are
        # serialized. Once serialized, the pending-request check below ensures
        # at most one pending request to join an organization can exist.
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            already_pending = (
                self.organization.invitations.get_pending_requests()
                .filter(user=user)
                .exists()
            )
            if already_pending:
                messages.info(
                    request,
                    _("You already have a pending request to join this organization."),
                )
                return
            invitation = self.organization.invitations.create(
                email=user.email, user=user, request=True
            )

        messages.success(
            request,
            _(
                "Request to join the organization sent!<br><br>"
                "We strongly recommend reaching out directly to one or all of "
                "the admins listed below to ensure your request is approved "
                "quickly. If all of the admins shown below have left the "
                "organization, please "
                '<a href="mailto:info@muckrock.com">contact support</a> '
                "for assistance.<br><br>"
            ),
        )
        invitation.send()

    def handle_leave(self, request):
        is_member = self.organization.has_member(self.request.user)
        can_manage = request.user.has_perm(
            "organizations.can_manage_members", self.organization
        )
        userid = request.POST.get("userid")
        user_left = False
        if userid:
            if userid == str(request.user.id) and is_member:
                # Users removing themselves
                request.user.memberships.filter(organization=self.organization).delete()
                messages.success(request, _("You left the organization"))
                user_left = True
            elif can_manage:
                # User with can_manage_members permission removing another user
                user_model = get_user_model()
                try:
                    target_user = user_model.objects.get(pk=userid)
                    target_user.memberships.filter(
                        organization=self.organization
                    ).delete()

                    # Log staff action to activity stream
                    new_action(
                        actor=request.user,
                        verb="removed member from organization",
                        action_object=target_user,
                        target=self.organization,
                    )

                    messages.success(
                        request,
                        _("%(username)s left the organization")
                        % {"username": target_user.username},
                    )
                except user_model.DoesNotExist:
                    messages.error(request, _("User not found"))
            else:
                # Only users with can_manage_members can remove other users
                messages.error(
                    request, _("You do not have permission to remove other users")
                )
        elif is_member:
            # User removing themselves (no userid provided)
            request.user.memberships.filter(organization=self.organization).delete()
            messages.success(request, _("You left the organization"))
            user_left = True

        # Redirect to profile if the user left a private org they can no
        # longer view, otherwise redirect following default behavior
        if user_left and self.organization.private:
            return redirect(request.user)
        return None

    def handle_enable_autojoin(self, request):
        if not request.user.has_perm(
            "organizations.can_manage_domains", self.organization
        ):
            messages.error(request, _("You do not have permission to manage auto-join"))
            return None
        self.organization.allow_auto_join = True
        self.organization.save()
        messages.success(request, _("Auto-join has been enabled"))
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def handle_disable_autojoin(self, request):
        if not request.user.has_perm(
            "organizations.can_manage_domains", self.organization
        ):
            messages.error(request, _("You do not have permission to manage auto-join"))
            return None
        self.organization.allow_auto_join = False
        self.organization.save()
        messages.success(request, _("Auto-join has been disabled"))
        return None

    def _sync_wix_for_org(self, org, plan):
        """Queue a Wix sync for every user in *org* using *plan*."""
        for wix_user in org.users.all():
            sync_wix.delay(org.pk, plan.pk, wix_user.pk)

    def handle_sync_wix(self, request):
        if not self.request.user.is_staff:
            return

        org = self.organization
        triggered = False

        # Direct Wix plans on this org
        for sub in org.subscriptions.filter(plan__wix=True).select_related("plan"):
            self._sync_wix_for_org(org, sub.plan)
            triggered = True

            # Cascade to member orgs and child orgs when this org shares resources
            if org.share_resources:
                for member_org in org.members.all():
                    self._sync_wix_for_org(member_org, sub.plan)
                for child_org in org.children.all():
                    self._sync_wix_for_org(child_org, sub.plan)

        # Inherited Wix plans via resource-sharing groups / parent orgs
        for _group, plan in org.get_wix_plans_from_groups():
            self._sync_wix_for_org(org, plan)
            triggered = True

        if triggered:
            messages.success(request, _("Wix sync started"))

    def handle_remove_member_org(self, request):
        """Removes a member organization from a group.
        Called by the group Remove action and the member Leave action."""

        org = self.organization
        member_slug = request.POST.get("member_org")
        user = request.user

        try:
            member_org = org.members.get(slug=member_slug)
        except Organization.DoesNotExist:
            messages.error(request, _("Organization not found"))
            return

        can_manage_member_orgs = user.has_perm(
            "organizations.can_manage_member_orgs", org
        )
        can_manage_groups = user.has_perm("organizations.can_manage_groups", member_org)

        # The user taking the action must have permission on either the group org or the member org
        if not can_manage_member_orgs and not can_manage_groups:
            messages.error(
                request, _("You do not have permission to remove this membership")
            )
            return

        org.members.remove(member_org)

        if can_manage_groups:
            new_action(
                actor=user,
                verb="left group",
                action_object=self.organization,
                target=member_org,
            )
        else:
            new_action(
                actor=user,
                verb="removed group member",
                action_object=member_org,
                target=self.organization,
            )

        messages.info(
            request,
            _("%(member)s is no longer a member of %(group)s")
            % {"member": member_org.name, "group": org.name},
        )

    def _get_invitation(self, request):
        org = self.organization
        can_manage_groups = request.user.has_perm(
            "organizations.can_manage_groups", org
        )

        if not can_manage_groups:
            messages.error(
                request, _("You do not have permission to accept this invitation")
            )
            return None

        invitation_uuid = request.POST.get("invitation")

        try:
            invitation = OrganizationInvitation.objects.get(
                uuid=invitation_uuid, to_organization=org
            )
        except OrganizationInvitation.DoesNotExist:
            messages.error(request, _("Invitation not found"))
            return None

        return invitation

    def handle_accept_group_invitation(self, request):
        invitation = self._get_invitation(request)

        if not invitation:
            return

        invitation.accept()

        member_org = self.organization
        group_org = invitation.from_organization

        new_action(
            actor=request.user,
            verb="joined group",
            action_object=group_org,
            target=member_org,
        )

        messages.success(
            request,
            _("%(member)s is now a member of %(group)s")
            % {"member": member_org.name, "group": group_org.name},
        )

    def handle_reject_group_invitation(self, request):
        invitation = self._get_invitation(request)

        if not invitation:
            return

        invitation.reject()

        member_org = self.organization
        group_org = invitation.from_organization

        new_action(
            actor=request.user,
            verb="rejected group invitation",
            action_object=group_org,
            target=member_org,
        )

        messages.info(request, _("Invitation rejected"))

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.organization = self.object

        if not self.request.user.is_authenticated:
            return redirect(self.organization)
        action = request.POST.get("action")
        if action == "join":
            self.handle_join(request)
        elif action == "leave":
            response = self.handle_leave(request)
            if response:
                return response
        elif action == "sync_wix":
            self.handle_sync_wix(request)
        elif action == "enable_autojoin":
            result = self.handle_enable_autojoin(request)
            if result:
                return result
        elif action == "disable_autojoin":
            self.handle_disable_autojoin(request)
        elif action == "remove_member_org":
            self.handle_remove_member_org(request)
        elif action == "accept_group_invitation":
            self.handle_accept_group_invitation(request)
            return redirect(self.organization)
        elif action == "reject_group_invitation":
            self.handle_reject_group_invitation(request)
            return redirect(self.organization)
        return get_redirect_url(request, redirect(self.organization))


class List(ListView):
    model = Organization
    paginate_by = ORG_PAGINATION

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(individual=False)
            .get_viewable(self.request.user)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if not user.is_authenticated:
            return context

        context["invitations"] = []
        context["potential_orgs"] = []
        if user.is_authenticated:
            context["pending_requests"] = list(user.get_pending_requests())
            context["pending_invitations"] = InvitationAcceptForm.attach_to_invitations(
                list(user.get_pending_invitations()), user, request=self.request
            )
            context["potential_orgs"] = list(user.get_potential_organizations())

        context["has_pending"] = bool(
            context["pending_requests"]
            + context["pending_invitations"]
            + context["potential_orgs"]
        )
        context["admin_orgs"] = list(
            user.organizations.filter(individual=False, memberships__admin=True)
        )
        context["other_orgs"] = list(
            user.organizations.filter(
                individual=False, memberships__admin=False
            ).get_viewable(self.request.user)
        )
        context["potential_organizations"] = list(user.get_potential_organizations())
        context["pending_invitations"] = InvitationAcceptForm.attach_to_invitations(
            list(user.get_pending_invitations()), user, request=self.request
        )
        context["has_verified_email"] = user.has_verified_email()

        return context


def autocomplete(request):
    # This should be replaced by a real API
    query = request.GET.get("q")
    page = request.GET.get("page")
    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1

    orgs = Organization.objects.filter(individual=False).get_viewable(request.user)
    if query:
        # Prioritize showing things that start with query
        orgs = (
            orgs.filter(name__icontains=query)
            .annotate(pos=StrIndex(Lower("name"), Lower(V(query))))
            .order_by("pos", "slug")
        )

    data = {
        "data": [
            {"name": o.name, "slug": o.slug, "avatar": o.avatar_url}
            for o in orgs[((page - 1) * ORG_PAGINATION) : (page * ORG_PAGINATION)]
        ]
    }
    return JsonResponse(data)
