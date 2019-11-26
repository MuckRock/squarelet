# Third Party
from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import DjangoObjectPermissions, IsAdminUser

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import Invitation, Membership, Plan

# Local
from .models import Charge, Organization
from .serializers import (
    ChargeSerializer,
    OrganizationSerializer,
    PressPassInvitationSerializer,
    PressPassMembershipSerializer,
    PressPassNestedInvitationSerializer,
    PressPassOrganizationSerializer,
    PressPassPlanSerializer,
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
        """Only fetch both organizations and memberships viewable to this user"""
        organization = get_object_or_404(
            Organization, uuid=self.kwargs["organization_uuid"]
        )
        return organization.memberships.all()


class PressPassNestedInvitationViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    queryset = Invitation.objects.none()
    serializer_class = PressPassNestedInvitationSerializer
    permission_classes = (DjangoObjectPermissions,)

    def get_queryset(self):
        """Only fetch both organizations and inivtations viewable to this user"""
        organization = get_object_or_404(
            Organization, uuid=self.kwargs["organization_uuid"]
        )
        return organization.invitations.all()


class PressPassInvitationViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = Invitation.objects.all()
    serializer_class = PressPassInvitationSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "uuid"

    def perform_update(self, serializer):
        """Accept or reject the invitation"""
        if serializer.data.get("accept"):
            serializer.instance.accept(self.request.user)
        elif serializer.data.get("reject"):
            serializer.instance.reject()


class PressPassPlanViewSet(viewsets.ModelViewSet):
    queryset = Plan.objects.all()
    serializer_class = PressPassPlanSerializer
    permission_classes = (DjangoObjectPermissions,)
