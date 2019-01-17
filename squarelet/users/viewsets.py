# Django
from django.db.models.query import Prefetch

# Third Party
from allauth.account.models import EmailAddress
from allauth.account.utils import setup_user_email
from rest_framework import status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

# Squarelet
from squarelet.oidc.permissions import ScopePermission

# Local
from .models import User
from .serializers import UserReadSerializer, UserWriteSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related(
        "organizations",
        Prefetch(
            "emailaddress_set",
            queryset=EmailAddress.objects.filter(primary=True),
            to_attr="primary_emails",
        ),
    )
    permission_classes = (ScopePermission,)
    read_scopes = ("read_user",)
    write_scopes = ("write_user",)

    def get_serializer_class(self):
        # The only actions expected are create and retrieve
        # If we add other write actions, update this method
        if self.action == "create":
            return UserWriteSerializer
        else:
            return UserReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        headers = self.get_success_headers(serializer.data)
        setup_user_email(request, user, [])
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )
