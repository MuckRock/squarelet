# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Value as V
from django.db.models.functions import Lower, StrIndex
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView

# Standard Library
import logging

# Squarelet
from squarelet.core.mixins import AdminLinkMixin
from squarelet.core.utils import (
    get_redirect_url,
    is_rate_limited,
)
from squarelet.organizations.models import (
    Invitation,
    Membership,
    Organization,
)
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
        if self.request.user.is_authenticated:
            context["is_admin"] = self.object.has_admin(self.request.user)
            context["is_member"] = self.object.has_member(self.request.user)

            context["requested_invite"] = self.request.user.invitations.filter(
                organization=self.object
            ).get_pending_requests()
            if context["is_admin"]:
                context["invite_count"] = (
                    self.object.invitations.get_pending_requests().count()
                )

            # Rejected join requests
            context["rejected_invite"] = self.request.user.invitations.filter(
                organization=self.object
            ).get_rejected_requests()

            context["can_auto_join"] = (
                self.request.user.can_auto_join(self.object)
                and not context["is_member"]
            )

        users = self.object.users.all()
        admins = users.filter(memberships__admin=True)
        if context.get("is_member"):
            context["users"] = users.order_by("-memberships__admin", "username")
        else:
            context["users"] = admins
        context["admins"] = admins

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
                f"You have reached the limit of {settings.ORG_JOIN_REQUEST_LIMIT} "
                "join requests in the last "
                f"{settings.ORG_JOIN_REQUEST_WINDOW // 60} minutes. "
                "Please try again later.",
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
