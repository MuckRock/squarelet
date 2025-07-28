# Django
from django.db.models import Prefetch

# Third Party
from allauth.account.models import EmailAddress
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

# Squarelet
from squarelet.organizations.models import Membership
from squarelet.users.fe_api.serializers import UserSerializer
from squarelet.users.models import User


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.prefetch_related(
        Prefetch(
            "memberships", queryset=Membership.objects.select_related("organization")
        ),
        Prefetch(
            "emailaddress_set",
            queryset=EmailAddress.objects.filter(primary=True),
            to_attr="primary_emails",
        ),
    ).order_by("created_at")
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = "id"
    swagger_schema = None

    def get_queryset(self):
        # Use the get_viewable() method from MembershipQuerySet
        visible_memberships = Membership.objects.get_viewable(self.request.user)

        # Fetch users from those memberships and return them
        return User.objects.filter(memberships__in=visible_memberships).distinct()
