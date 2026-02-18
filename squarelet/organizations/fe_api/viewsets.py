# Django
from django.db.models import Q
from django.db.models.aggregates import Count

# Third Party
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

# Squarelet
from squarelet.organizations.fe_api.permissions import (
    CanAcceptInvitation,
    CanCreateInvitation,
    CanRejectInvitation,
    CanResendInvitation,
    CanWithdrawInvitation,
)
from squarelet.organizations.fe_api.serializers import (
    InvitationSerializer,
    OrganizationSerializer,
)
from squarelet.organizations.models import Invitation, Organization


class OrganizationFilter(django_filters.FilterSet):
    verified_journalist = django_filters.BooleanFilter()

    class Meta:
        model = Organization
        fields = ["verified_journalist", "private", "individual"]


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        return (
            Organization.objects.get_viewable(self.request.user)
            .prefetch_related("users__memberships")
            .annotate(member_count=Count("users"))
        )

    serializer_class = OrganizationSerializer
    permission_classes = (AllowAny,)
    lookup_field = "id"
    swagger_schema = None

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = OrganizationFilter
    search_fields = ["name"]
    ordering_fields = ["name"]


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Invitation.objects.all()
    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated, CanCreateInvitation]

    def get_queryset(self):
        user = self.request.user
        verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )

        return (
            Invitation.objects.filter(
                accepted_at__isnull=True,
                rejected_at__isnull=True,
                withdrawn_at__isnull=True,
            )
            .filter(
                Q(user=user)
                | Q(email__in=verified_emails)
                | Q(
                    organization__memberships__user=user,
                    organization__memberships__admin=True,
                )
            )
            .distinct()
        )

    def partial_update(self, request, *args, **kwargs):
        invitation = self.get_object()
        action = request.data.get("action")
        user = request.user

        if action == "accept":
            # Check permission
            if not CanAcceptInvitation().has_object_permission(
                request, self, invitation
            ):
                raise PermissionDenied(
                    "You do not have permission to accept this invitation."
                )

            try:
                invitation.accept(user=user)
                return Response({"status": "invitation accepted"})
            except ValueError as error:
                return Response({"detail": str(error)}, status=400)

        elif action == "reject":
            if not CanRejectInvitation().has_object_permission(
                request, self, invitation
            ):
                raise PermissionDenied(
                    "You do not have permission to reject this invitation."
                )

            try:
                invitation.reject()
                return Response({"status": "invitation rejected"})
            except ValueError as error:
                return Response({"detail": str(error)}, status=400)

        elif action == "withdraw":
            if not CanWithdrawInvitation().has_object_permission(
                request, self, invitation
            ):
                raise PermissionDenied(
                    "You do not have permission to withdraw this invitation."
                )

            try:
                invitation.withdraw()
                return Response({"status": "invitation withdrawn"})
            except ValueError as error:
                return Response({"detail": str(error)}, status=400)

        elif action == "resend":
            if not CanResendInvitation().has_object_permission(
                request, self, invitation
            ):
                raise PermissionDenied(
                    "You do not have permission to resend this invitation."
                )

            invitation.send()
            return Response({"status": "invitation resent"})

        else:
            return Response(
                {
                    "detail": "Invalid action. Must be one of: "
                    "accept, reject, withdraw, resend."
                },
                status=400,
            )
