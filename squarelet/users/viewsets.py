
# Third Party
from rest_framework import viewsets

# Local
from ..oidc.permissions import ScopePermission
from .models import User
from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (ScopePermission,)
    read_scopes = ("read_user",)
    write_scopes = ("write_user",)
