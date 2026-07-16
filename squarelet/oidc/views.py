# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render

# Third Party
from oidc_provider.models import Client
from oidc_provider.views import AuthorizeView as BaseAuthorizeView
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

# Squarelet
from squarelet.oidc.models import ClientProfile
from squarelet.oidc.permissions import ScopePermission


class AuthorizeView(BaseAuthorizeView):
    """
    We customize the AuthorizeView to show additional information
    to users during the authorization flow.
    """

    DISMISS_SESSION_KEY = "verification_notice_dismissed"

    def get(self, request, *args, **kwargs):
        notice = self._verification_notice(request)
        if notice is not None:
            return notice
        return super().get(request, *args, **kwargs)

    def _verification_notice(self, request):
        """
        A client can enable ``ClientProfile.checks_verification``. When an
        unverified user authorizes such a client, we interpose an informational
        notice — carrying the client's own explanation — before consent, offering a
        path to request verification or to continue anyway. Unlike the onboarding
        pipeline, which only runs on a fresh login, this fires on every
        authorization, so it also reaches users who already have a Squarelet
        session. The notice is dismissable per session.
        """
        client = self._get_client(request)
        profile = self._get_client_profile(client)
        dismissed = request.session.get(self.DISMISS_SESSION_KEY, [])

        skip = (
            (profile is None or not profile.checks_verification)
            or not request.user.is_authenticated
            or request.user.verified_journalist()
            or client.client_id in dismissed
        )

        if skip:
            return None

        if request.GET.get("verification_ack"):
            # The user chose to continue; remember it for the session so we
            # don't re-prompt on subsequent authorizations, then proceed.
            request.session[self.DISMISS_SESSION_KEY] = dismissed + [client.client_id]
            request.session.modified = True
            return None

        # Show the verification notice to the user
        params = request.GET.copy()
        params["verification_ack"] = "1"
        user = request.user
        unverified_orgs = user.organizations.filter(
            individual=False, memberships__user=user
        ).order_by("name")
        return render(
            request,
            "oidc_provider/verification_notice.html",
            {
                "client": client,
                "verification_notice": profile.verification_notice,
                "continue_url": f"{request.path}?{params.urlencode()}",
                "has_verified_email": user.has_verified_email(),
                "unverified_orgs": unverified_orgs,
            },
        )

    @staticmethod
    def _get_client(request):
        client_id = request.GET.get("client_id")
        if not client_id:
            return None
        try:
            return Client.objects.select_related("clientprofile").get(
                client_id=client_id
            )
        except Client.DoesNotExist:
            return None

    @staticmethod
    def _get_client_profile(client):
        if client is None:
            return None
        try:
            return client.clientprofile
        except ClientProfile.DoesNotExist:
            return None


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
