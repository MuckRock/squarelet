# Third Party
import django_filters
from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAdminUser

# Squarelet
from squarelet.core.permissions import DjangoObjectPermissionsOrAnonReadOnly
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.choices import ChangeLogReason
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
    queryset = Organization.objects.none()
    serializer_class = PressPassOrganizationSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)
    lookup_field = "uuid"

    # XXX if update max_users, need to update subscriptions

    def get_queryset(self):
        return Organization.objects.get_viewable(self.request.user)

    def perform_create(self, serializer):
        organization = serializer.save()
        organization.add_creator(self.request.user)
        organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=self.request.user,
            to_plan=organization.plan,
            to_max_users=organization.max_users,
        )

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
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)
    lookup_field = "user__uuid"

    def get_queryset(self):
        """Only fetch both organizations and memberships viewable to this user"""
        organization = get_object_or_404(
            Organization.objects.get_viewable(self.request.user),
            uuid=self.kwargs["organization_uuid"],
        )
        return organization.memberships.all()


class PressPassNestedInvitationViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """
    The nested invitation view set is for requesting to join an organization,
    inviting somebody to join your organization and seeing who has requested to join
    your organization
    """

    queryset = Invitation.objects.none()
    serializer_class = PressPassNestedInvitationSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)

    def get_queryset(self):
        """Only fetch both organizations and inivtations viewable to this user"""
        organization = get_object_or_404(
            Organization.objects.get_viewable(self.request.user),
            uuid=self.kwargs["organization_uuid"],
        )
        if organization.has_admin(self.request.user):
            return organization.invitations.all()
        else:
            return organization.invitations.none()

    def perform_create(self, serializer):
        organization = get_object_or_404(
            Organization.objects.get_viewable(self.request.user),
            uuid=self.kwargs["organization_uuid"],
        )
        # Admins will set an email address to invite and we will send the invitation
        if organization.has_admin(self.request.user):
            invitation = serializer.save(organization=organization, request=False)
            invitation.send()
        # Users can also request to join - no email address is used, we set
        # `user` to the current user
        else:
            invitation = serializer.save(
                organization=organization, request=True, user=self.request.user
            )


class PressPassInvitationViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """
    The stand alone invitation viewset is for viewing and accepting or rejecting
    your invitations
    """

    queryset = Invitation.objects.all()
    serializer_class = PressPassInvitationSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)
    lookup_field = "uuid"

    def perform_update(self, serializer):
        """Accept or reject the invitation"""
        if serializer.data.get("accept"):
            serializer.instance.accept(self.request.user)
        elif serializer.data.get("reject"):
            serializer.instance.reject()


class PressPassPlanViewSet(viewsets.ReadOnlyModelViewSet):
    # XXX
    queryset = Plan.objects.all()
    serializer_class = PressPassPlanSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)


class PressPassEntitlmentViewSet(viewsets.ReadOnlyModelViewSet):
    # XXX
    queryset = Entitlement.objects.all()
    serializer_class = PressPassEntitlmentSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)


class PressPassSubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.none()
    serializer_class = PressPassSubscriptionSerializer
    permission_classes = (DjangoObjectPermissionsOrAnonReadOnly,)
    lookup_field = "plan_id"

    # XXX business logic

    def get_queryset(self):
        """Only fetch both organizations and subscriptions viewable to this user"""
        organization = get_object_or_404(
            Organization, uuid=self.kwargs["organization_uuid"]
        )
        # XXX
        return organization.subscriptions.all()
