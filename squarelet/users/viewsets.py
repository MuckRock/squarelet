# Django
from django.db.models.query import Prefetch

# Third Party
from allauth.account.models import EmailAddress
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

# Squarelet
from squarelet.oidc.permissions import ScopePermission

# Local
from .models import User
from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related(
        "organizations",
        Prefetch(
            "emailaddress_set",
            queryset=EmailAddress.objects.filter(primary=True),
            to_attr="primary_emails",
        ),
    )
    serializer_class = UserSerializer
    # permission_classes = (ScopePermission,)
    permission_classes = (IsAdminUser,)
    read_scopes = ("read_user",)
    write_scopes = ("write_user",)
