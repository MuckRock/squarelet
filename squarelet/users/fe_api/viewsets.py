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
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = "id"
    swagger_schema = None

    def get_queryset(self):
        return User.objects.prefetch_related("organizations")
