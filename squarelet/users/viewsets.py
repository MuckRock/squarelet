# Django
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.query import Prefetch
from django.http.response import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# Third Party
import sesame.utils
from allauth.account import app_settings as allauth_settings
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.account.utils import complete_signup, setup_user_email
from dj_rest_auth.registration.views import RegisterView
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import DjangoObjectPermissions, IsAdminUser
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import AccessToken

# Squarelet
from squarelet.core.mail import send_mail
from squarelet.oidc.permissions import ScopePermission
from squarelet.organizations.models import Membership
from squarelet.users.models import User
from squarelet.users.serializers import (
    PressPassUserSerializer,
    PressPassUserWriteSerializer,
    UserReadSerializer,
    UserWriteSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related(
        Prefetch("memberships", queryset=Membership.objects.all()),
        Prefetch(
            "emailaddress_set",
            queryset=EmailAddress.objects.filter(primary=True),
            to_attr="primary_emails",
        ),
    ).order_by("created_at")
    permission_classes = (ScopePermission | IsAdminUser,)
    read_scopes = ("read_user",)
    write_scopes = ("write_user",)
    lookup_field = "individual_organization_id"
    lookup_url_kwarg = "uuid"
    swagger_schema = None

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
    swagger_schema = None

    def retrieve(self, request, pk=None):
        # pylint: disable=invalid-name
        try:
            user = get_object_or_404(User, individual_organization_id=pk)
        except ValidationError:
            raise Http404
        return Response(sesame.utils.get_parameters(user))


class AccessTokenViewSet(viewsets.ViewSet):
    permission_classes = (ScopePermission,)
    read_scopes = ("read_auth_token",)
    swagger_schema = None

    def retrieve(self, request, pk=None):
        # pylint: disable=invalid-name
        try:
            user = get_object_or_404(User, individual_organization_id=pk)
        except ValidationError:
            raise Http404
        token = AccessToken.for_user(user)
        token.payload["permissions"] = request.query_params.get(
            "permissions", ""
        ).split(" ")
        return Response({"access_token": str(token)})


class PressPassUserViewSet(
    # Cannot create or destroy users
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all()
    permission_classes = (DjangoObjectPermissions,)
    lookup_field = "individual_organization_id"
    lookup_url_kwarg = "uuid"
    serializer_class = PressPassUserSerializer

    def get_object(self):
        """Allow one to lookup themselves by specifying `me` as the pk"""
        if self.kwargs["uuid"] == "me" and self.request.user.is_authenticated:
            return self.request.user
        else:
            return super().get_object()


class PressPassRegisterView(RegisterView):
    serializer_class = PressPassUserWriteSerializer

    def get_response_data(self, user):
        if (
            allauth_settings.EMAIL_VERIFICATION
            == allauth_settings.EmailVerificationMethod.MANDATORY
        ):
            return {"detail": _("Verification e-mail sent.")}
        return {}

    def perform_create(self, serializer):
        data = serializer.data
        data["source"] = "presspass"

        # Because the django-rest-auth serializer only supports usernames, emails,
        # and passwords, we must set the user's name to some default.
        data["name"] = ""

        # The serializer uses write-only fields for passwords, which makes sense.
        # This probably means we shouldn't use rest auth for registration at all.
        # We should write our own registration view from scratch.
        data["password1"] = self.request.data["password1"]

        # Set to none until we have plans developed
        data["plan"] = None

        # Set to News Catalyst until we setup organization registration
        data["organization_name"] = "News Catalyst"

        user, _group_organization, _error = get_user_model().objects.register_user(data)
        user.save()

        complete_signup(self.request, user, allauth_settings.EMAIL_VERIFICATION, None)

        return user
