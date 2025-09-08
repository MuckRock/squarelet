# Standard
# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt

# Third Party
from oidc_provider import settings, views
from oidc_provider.lib import endpoints
from oidc_provider.lib.errors import TokenError, UserAuthError
from oidc_provider.lib.utils.token import create_id_token, create_token, encode_id_token
from oidc_provider.models import Client
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

# Squarelet
from squarelet.oidc.permissions import ScopePermission


class TokenEndpoint(endpoints.token.TokenEndpoint):
    """Override OIDC token endpoint to use our JWT tokens"""

    def create_code_response_dic(self):
        # See https://tools.ietf.org/html/rfc6749#section-4.1

        token = create_token(
            user=self.code.user, client=self.code.client, scope=self.code.scope
        )

        if self.code.is_authentication:
            id_token_dic = create_id_token(
                user=self.code.user,
                aud=self.client.client_id,
                token=token,
                nonce=self.code.nonce,
                at_hash=token.at_hash,
                request=self.request,
                scope=token.scope,
            )
        else:
            id_token_dic = {}
        token.id_token = id_token_dic

        # Store the token.
        token.save()

        jwt = RefreshToken.for_user(self.code.user)

        # We don't need to store the code anymore.
        self.code.delete()

        dic = {
            "access_token": str(jwt.access_token),
            "refresh_token": str(jwt),
            "token_type": "bearer",
            "expires_in": settings.get("OIDC_TOKEN_EXPIRE"),
            "id_token": encode_id_token(id_token_dic, token.client),
        }

        return dic


class TokenView(views.TokenView):
    """Override OIDC provider token view to use our JWT tokens"""

    def post(self, request, *args, **kwargs):
        token = TokenEndpoint(request)

        try:
            token.validate_params()

            dic = token.create_response_dic()

            return TokenEndpoint.response(dic)

        except TokenError as error:
            return TokenEndpoint.response(error.create_dict(), status=400)
        except UserAuthError as error:
            return TokenEndpoint.response(error.create_dict(), status=403)


token_view = csrf_exempt(TokenView.as_view())


class OIDCRedirectURIUpdater(APIView):
    """
    API endpoint to add or remove redirect URIs for OIDC clients on staging.

    **Request Method:**
    PATCH /api/clients/{client_id}/redirect_uris/

    **Expected JSON payload:**
    ```json
    {
        "action": "add",
        "redirect_uris": [
            "https://example.com/callback",
            "https://another.com/redirect"
        ]
    }
    ```
    """

    permission_classes = [ScopePermission | IsAdminUser]

    write_scopes = ("write_client_redirect_uris",)

    def patch(self, request, client_id, *args, **kwargs):
        return self._handle_request(request, client_id)

    def _handle_request(self, request, client_id):
        try:
            action = request.data.get("action")
            uris_to_modify = request.data.get("redirect_uris")

            if not action or action not in ["add", "remove"]:
                return Response(
                    {
                        "error": "Invalid or missing 'action'. "
                        "Must be 'add' or 'remove'."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if (
                not uris_to_modify
                or not isinstance(uris_to_modify, list)
                or not all(isinstance(uri, str) for uri in uris_to_modify)
            ):
                return Response(
                    {
                        "error": "Invalid or missing 'redirect_uris'. "
                        "It must be a list of strings."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValidationError, TypeError) as exc:
            return Response(
                {"error": f"Invalid request format: {str(exc)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            try:
                client = Client.objects.select_for_update().get(id=client_id)
            except Client.DoesNotExist:
                return Response(
                    {"error": f"OIDC client with ID {client_id} not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            current_uris = client.redirect_uris or []

            if action == "add":
                for uri in uris_to_modify:
                    if uri not in current_uris:
                        current_uris.append(uri)
            elif action == "remove":
                current_uris = [
                    uri for uri in current_uris if uri not in uris_to_modify
                ]

            client.redirect_uris = current_uris
            client.save()

        return Response(
            {"message": "OIDC client redirect URIs updated successfully."},
            status=status.HTTP_200_OK,
        )
