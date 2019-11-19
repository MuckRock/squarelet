# Standard Library
from hashlib import sha224
from random import randint
from uuid import uuid4

# Third Party
from oidc_provider.models import Client, ResponseType
from rest_framework import viewsets
from rest_framework.permissions import DjangoObjectPermissions

# Squarelet
from squarelet.oidc.serializers import ClientSerializer


class ClientViewSet(viewsets.ModelViewSet):
    """Third party clients which would like to authenticate against Squarelet/PressPass
    OIDC server
    """

    queryset = Client.objects.none()
    serializer_class = ClientSerializer
    permission_classes = (DjangoObjectPermissions,)

    def get_queryset(self):
        return Client.objects.filter(owner=self.request.user).order_by("name")

    def perform_create(self, serializer):
        code_type, _created = ResponseType.objects.get_or_create(value="code")
        kwargs = {"owner": self.request.user, "response_types": [code_type]}
        kwargs["client_id"] = str(randint(1, 999999)).zfill(6)
        if serializer.initial_data["client_type"] == "confidential":
            kwargs["client_secret"] = sha224(uuid4().hex.encode()).hexdigest()
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        kwargs = {}
        if (
            serializer.initial_data.get("client_type", serializer.instance.client_type)
            == "confidential"
        ):
            if not serializer.instance.client_id:
                kwargs["client_id"] = str(randint(1, 999999)).zfill(6)
            if not serializer.instance.client_secret:
                kwargs["client_secret"] = sha224(uuid4().hex.encode()).hexdigest()
        serializer.save(**kwargs)
