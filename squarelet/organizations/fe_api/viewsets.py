# Third Party
# Django
from django.db.models import Q

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.fe_api.permissions import (
    CanAcceptInvitation,
    CanCreateInvitation,
    CanRejectInvitation,
    CanResendInvitation,
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
        return Organization.objects.select_related("_plan").get_viewable(
            self.request.user
        )

    serializer_class = OrganizationSerializer
    permission_classes = (IsAuthenticated,)
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
                accepted_at__isnull=True, rejected_at__isnull=True
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

    @action(detail=True, methods=["post"], permission_classes=[CanAcceptInvitation])
    def accept(self, request, *args, **kwargs):
        invitation = self.get_object()
        try:
            invitation.accept(user=request.user)
            return Response({"status": "invitation accepted"})
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[CanRejectInvitation])
    def reject(self, request, *args, **kwargs):
        invitation = self.get_object()
        try:
            invitation.reject()
            return Response({"status": "invitation rejected"})
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[CanResendInvitation])
    def resend(self, request, *args, **kwargs):
        invitation = self.get_object()
        invitation.send()
        return Response({"status": "invitation resent"})
