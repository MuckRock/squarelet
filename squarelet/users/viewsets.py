# Django
from django.core.exceptions import ValidationError
from django.db.models.query import Prefetch
from django.http.response import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Third Party
import sesame.utils
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.account.utils import setup_user_email
from rest_framework import status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

# Squarelet
from squarelet.core.mail import send_mail
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import Membership

# Local
from .models import User
from .serializers import UserReadSerializer, UserWriteSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related(
        Prefetch(
            "memberships",
            queryset=Membership.objects.select_related("organization__plan"),
        ),
        Prefetch(
            "emailaddress_set",
            queryset=EmailAddress.objects.filter(primary=True),
            to_attr="primary_emails",
        ),
    ).order_by("created_at")
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
        if not user.is_agency:
            email_address = EmailAddress.objects.get_primary(user)
            key = EmailConfirmationHMAC(email_address).key
            activate_url = reverse("account_confirm_email", args=[key])
            send_mail(
                subject=_("Welcome to MuckRock"),
                template="account/email/email_confirmation_signup_message.html",
                user=user,
                extra_context={"activate_url": activate_url, "minireg": True},
            )

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class UrlAuthTokenViewSet(viewsets.ViewSet):
    permission_classes = (ScopePermission,)
    read_scopes = ("read_auth_token",)

    def retrieve(self, request, pk=None):
        # pylint: disable=invalid-name
        try:
            user = get_object_or_404(User, pk=pk)
        except ValidationError:
            raise Http404
        return Response(sesame.utils.get_parameters(user))
