# Django
from django.conf import settings

# Third Party
from oidc_provider import views
from oidc_provider.lib import endpoints
from oidc_provider.lib.errors import TokenError, UserAuthError
from oidc_provider.lib.utils.token import create_id_token, create_token, encode_id_token
from rest_framework_simplejwt.tokens import RefreshToken


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
