# Django
from django.core.exceptions import ValidationError
from django.db import transaction

# Third Party
from oidc_provider.models import Client
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

# Squarelet
from squarelet.oidc.permissions import ScopePermission


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
