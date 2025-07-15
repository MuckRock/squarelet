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
    lookup_field = "individual_organization_id"
    lookup_url_kwarg = "uuid"
    swagger_schema = None
