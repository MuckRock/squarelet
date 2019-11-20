# Third Party
from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import DjangoObjectPermissions, IsAdminUser

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import Membership

# Local
from .models import Charge, Organization
from .serializers import (
    ChargeSerializer,
    OrganizationSerializer,
    PressPassMembershipSerializer,
    PressPassOrganizationSerializer,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    queryset = Organization.objects.select_related("plan")
    serializer_class = OrganizationSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_organization",)
    write_scopes = ("write_organization",)
    lookup_field = "uuid"
    swagger_schema = None


class ChargeViewSet(viewsets.ModelViewSet):
    queryset = Charge.objects.all()
    serializer_class = ChargeSerializer
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_charge",)
    write_scopes = ("write_charge",)
    swagger_schema = None


class PressPassOrganizationViewSet(
    # Cannot destroy organizations
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Organization.objects.select_related("plan")
    serializer_class = PressPassOrganizationSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "uuid"


class PressPassMembershipViewSet(
    # Cannot create memberships directly
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Membership.objects.none()
    serializer_class = PressPassMembershipSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "user_id"

    def get_queryset(self):
        """Only fetch both documents and notes viewable to this user"""
        organization = get_object_or_404(
            Organization, uuid=self.kwargs["organization_uuid"]
        )
        return organization.memberships.all()
