# Third Party
# Django
from django.db.models import Q

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import Charge, Invitation, Organization
from squarelet.organizations.permissions import (
    CanAcceptOrRejectInvitation,
    CanRevokeInvitation,
)
from squarelet.organizations.serializers import (
    ChargeSerializer,
    InvitationSerializer,
    OrganizationSerializer,
)


class OrganizationFilter(django_filters.FilterSet):
    verified_journalist = django_filters.BooleanFilter()

    class Meta:
        model = Organization
        fields = ["verified_journalist"]


class OrganizationViewSet(viewsets.ModelViewSet):
    # remove _plan after clients are updated
    queryset = Organization.objects.select_related("_plan")
    serializer_class = OrganizationSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_organization",)
    write_scopes = ("write_organization",)
    lookup_field = "uuid"
    swagger_schema = None

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = OrganizationFilter
    search_fields = ["name"]
    ordering_fields = ["name"]


class ChargeViewSet(viewsets.ModelViewSet):
    queryset = Charge.objects.all()
    serializer_class = ChargeSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_charge",)
    write_scopes = ("write_charge",)
    swagger_schema = None


class InvitationViewSet(viewsets.ModelViewSet):
    queryset = Invitation.objects.all()
    serializer_class = InvitationSerializer
    permission_classes = [IsAdminUser]  # restrict to staff users only
    lookup_field = "uuid"

    def get_queryset(self):
        user = self.request.user
        verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )

        return Invitation.objects.filter(
            accepted_at__isnull=True, rejected_at__isnull=True
        ).filter(
            Q(user=user)
            | Q(email__in=verified_emails)
            | Q(
                organization__memberships__user=user,
                organization__memberships__admin=True,
            )
        )

    @action(
        detail=True, methods=["post"], permission_classes=[CanAcceptOrRejectInvitation]
    )
    def accept(self, request):
        invitation = self.get_object()
        try:
            invitation.accept(user=request.user)
            return Response({"status": "invitation accepted"})
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(
        detail=True, methods=["post"], permission_classes=[CanAcceptOrRejectInvitation]
    )
    def reject(self, request):
        invitation = self.get_object()
        try:
            invitation.reject()
            return Response({"status": "invitation rejected"})
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[CanRevokeInvitation])
    def revoke(self, request):
        """
        Used to revoke a request to join an organization by a user
        or revoke a pending invite sent by an admin
        """
        invitation = self.get_object()
        try:
            invitation.reject()
            return Response({"status": "Invitation revoked"})
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
