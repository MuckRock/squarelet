# Django
from django.utils import timezone

# Third Party
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.filters import OrganizationFilter
from squarelet.organizations.models import Charge, Organization
from squarelet.organizations.serializers import (
    ChargeSerializer,
    OrganizationDetailSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    queryset = Organization.objects.prefetch_related(
        "subtypes__type", "users__memberships", "groups"
    )
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_organization",)
    write_scopes = ("write_organization",)
    lookup_field = "uuid"
    swagger_schema = None
    filterset_class = OrganizationFilter

    def get_serializer_class(self):
        if self.action == "retrieve":
            return OrganizationDetailSerializer

        return OrganizationSerializer

    def get_queryset(self):
        """Filter by consent if required"""
        if self.request.auth:
            client = self.request.auth.client
            if client and client.require_consent:
                return self.queryset.filter(
                    users__userconsent__client=client,
                    users__userconsent__expires_at__gt=timezone.now(),
                )
        return self.queryset


class ChargeViewSet(viewsets.ModelViewSet):
    queryset = Charge.objects.all()
    serializer_class = ChargeSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_charge",)
    write_scopes = ("write_charge",)
    swagger_schema = None
