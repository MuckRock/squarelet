
# Third Party
from oidc_provider.lib.utils.oauth2 import extract_access_token
from oidc_provider.models import Token
from rest_framework import authentication, exceptions


class OidcOauth2Authentication(authentication.BaseAuthentication):
    """Authentcation backend for django rest framework for checking against OIDC
    provider's oAuth2 access token"""

    def authenticate(self, request):
        access_token = extract_access_token(request)

        if not access_token:
            # not this kind of auth
            return None

        try:
            oauth2_token = Token.objects.get(access_token=access_token)
        except Token.DoesNotExist:
            raise exceptions.AuthenticationFailed("The oauth2 token is invalid")

        if oauth2_token.has_expired():
            raise exceptions.AuthenticationFailed("The oauth2 token has expired")

        return oauth2_token.user, oauth2_token
