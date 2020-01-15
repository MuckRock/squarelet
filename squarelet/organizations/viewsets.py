# Third Party
import django_filters
from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import DjangoObjectPermissions, IsAdminUser

# Squarelet
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import (
    Charge,
    Entitlement,
    Invitation,
    Membership,
    Organization,
    Plan,
    Subscription,
)
from squarelet.organizations.serializers import (
    ChargeSerializer,
    OrganizationSerializer,
    PressPassEntitlmentSerializer,
    PressPassInvitationSerializer,
    PressPassMembershipSerializer,
    PressPassNestedInvitationSerializer,
    PressPassOrganizationSerializer,
    PressPassPlanSerializer,
    PressPassSubscriptionSerializer,
)
from squarelet.users.models import User


class OrganizationViewSet(viewsets.ModelViewSet):
    # XXX
    queryset = Organization.objects.select_related("_plan")
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
    # XXX
    queryset = Organization.objects.select_related("_plan")
    serializer_class = PressPassOrganizationSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "uuid"

    class Filter(django_filters.FilterSet):
        user = django_filters.ModelChoiceFilter(
            queryset=User.objects.all(), to_field_name="uuid", field_name="users"
        )

        class Meta:
            model = Organization
            fields = ["user"]

    filterset_class = Filter


class PressPassMembershipViewSet(
    # Cannot create memberships directly - must use invitations
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Membership.objects.none()
    serializer_class = PressPassMembershipSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "user__uuid"

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
    # XXX
    queryset = Plan.objects.all()
    serializer_class = PressPassPlanSerializer
    permission_classes = (DjangoObjectPermissions,)


class PressPassEntitlmentViewSet(viewsets.ModelViewSet):
    # XXX
    queryset = Entitlement.objects.all()
    serializer_class = PressPassEntitlmentSerializer
    permission_classes = (DjangoObjectPermissions,)


class PressPassSubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.none()
    serializer_class = PressPassSubscriptionSerializer
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "plan_id"

    # XXX business logic

    def get_queryset(self):
        """Only fetch both organizations and subscriptions viewable to this user"""
        organization = get_object_or_404(
            Organization, uuid=self.kwargs["organization_uuid"]
        )
        # XXX
        return organization.subscriptions.all()
