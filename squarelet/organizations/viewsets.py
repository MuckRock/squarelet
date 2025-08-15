# Third Party
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

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
        "subtypes__type", "users__memberships"
    )
    serializer_class = OrganizationSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_organization",)
    write_scopes = ("write_organization",)
    lookup_field = "uuid"
    swagger_schema = None
    filterset_class = OrganizationFilter

    def retrieve(self, request, *args, **kwargs):
        serializer = OrganizationDetailSerializer(self.get_object(), many=False)
        return Response(serializer.data)


class ChargeViewSet(viewsets.ModelViewSet):
    queryset = Charge.objects.all()
    serializer_class = ChargeSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_charge",)
    write_scopes = ("write_charge",)
    swagger_schema = None
