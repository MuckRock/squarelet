# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
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
from squarelet.organizations.models import Invitation, Membership, Organization, Plan
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
        if self.request.user.is_authenticated:
            context["is_admin"] = org.has_admin(self.request.user)
            context["is_member"] = org.has_member(self.request.user)

            if context["is_admin"] or self.request.user.is_staff:
                context["pending_requests"] = org.invitations.get_pending_requests()
                context["pending_invitations"] = (
                    org.invitations.get_pending_invitations()
                )

            # Join requests
            context["requested_invite"] = self.request.user.invitations.filter(
                organization=org
            ).get_pending_requests()

            # Rejected requests
            context["rejected_invite"] = self.request.user.invitations.filter(
                organization=org
            ).get_rejected_requests()

            context["can_auto_join"] = (
                self.request.user.can_auto_join(org) and not context["is_member"]
            )

        users = org.member_users(self.request)
        admins = [
            u for u in users if u.org_membership_list and u.org_membership_list[0].admin
        ]
        if context.get("is_member"):
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

        # Add member counts
        context["member_count"] = len(users)
        context["admin_count"] = len(admins)

        # Plan context - get card, next charge date,
        # and cancelled status for active subscription
        if current_plan and subscription:
            customer = getattr(org, "customer", None)
            if callable(customer):
                customer = customer()
            context["current_plan_card"] = getattr(customer, "card", None)
            # Stripe subscription may have next charge date
            stripe_sub = getattr(subscription, "stripe_subscription", None)
            if stripe_sub:
                # Try to get next charge date from Stripe subscription
                time_stamp = getattr(stripe_sub, "current_period_end", None)
                if time_stamp:
                    tz_datetime = datetime.fromtimestamp(
                        time_stamp, tz=timezone.get_current_timezone()
                    )
                    context["current_plan_next_charge_date"] = tz_datetime.date()
            # Check if the plan is cancelled
            context["current_plan_cancelled"] = getattr(subscription, "cancelled", None)

        # Verification context - let template handle URL generation
        context["show_verification_request"] = (
            context.get("is_admin") or self.request.user.is_staff
        ) and not self.object.verified_journalist

        # Security settings context (read-only for now)
        if context.get("is_admin") or self.request.user.is_staff:
            context["security_settings"] = {
                "allow_auto_join": self.object.allow_auto_join,
                "has_email_domains": self.object.domains.exists(),
            }

        return context

    def handle_join(self, request):
        self.organization = self.get_object()
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

        # Create join request, assuming they aren't rate limited
        invitation = self.organization.invitations.create(
            email=request.user.email, user=request.user, request=True
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
        self.organization = self.get_object()
        is_member = self.organization.has_member(self.request.user)
        userid = request.POST.get("userid")
        if userid:
            if userid == str(request.user.id) and is_member:
                # Users removing themselves
                request.user.memberships.filter(organization=self.organization).delete()
                messages.success(request, _("You left the organization"))
            elif request.user.is_staff:
                # Staff removing another user
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
                # Only staff can remove other users
                messages.error(
                    request, _("You do not have permission to remove other users")
                )
        elif is_member:
            # User removing themselves (no userid provided)
            request.user.memberships.filter(organization=self.organization).delete()
            messages.success(request, _("You left the organization"))

    def handle_sync_wix(self, request):
        self.organization = self.get_object()
        if self.request.user.is_staff and self.organization.plan.wix:
            for wix_user in self.organization.users.all():
                sync_wix.delay(
                    self.organization.pk,
                    self.organization.plan.pk,
                    wix_user.pk,
                )
            messages.success(request, _("Wix sync started"))

    def post(self, request, *args, **kwargs):
        self.organization = self.get_object()

        if not self.request.user.is_authenticated:
            return redirect(self.organization)
        if request.POST.get("action") == "join":
            self.handle_join(request)
        elif request.POST.get("action") == "leave":
            self.handle_leave(request)
        elif request.POST.get("action") == "sync_wix":
            self.handle_sync_wix(request)
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
            context["pending_invitations"] = list(user.get_pending_invitations())
            context["potential_orgs"] = list(user.get_potential_organizations())

        context["has_pending"] = bool(
            context["pending_requests"]
            + context["pending_invitations"]
            + context["potential_orgs"]
        )
        context["has_verified_email"] = bool(user.get_verified_emails())
        context["admin_orgs"] = list(
            user.organizations.filter(individual=False, memberships__admin=True)
        )
        context["other_orgs"] = list(
            user.organizations.filter(
                individual=False, memberships__admin=False
            ).get_viewable(self.request.user)
        )
        context["potential_organizations"] = list(user.get_potential_organizations())
        context["pending_invitations"] = list(user.get_pending_invitations())

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
