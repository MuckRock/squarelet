# Django
from django.core.exceptions import PermissionDenied

# Third Party
from allauth.socialaccount import app_settings
from allauth.socialaccount.helpers import (
    complete_social_login,
    render_authentication_error,
)
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.base import AuthError, ProviderException
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)
from allauth.utils import get_request_param
from requests.exceptions import RequestException

# Squarelet
from squarelet.providers.github_app.provider import GitHubAppProvider


class GitHubAppOAuth2Adapter(GitHubOAuth2Adapter):
    provider_id = GitHubAppProvider.id
    settings = app_settings.PROVIDERS.get(provider_id, {})


class GitHubAppCallbackView(OAuth2CallbackView):
    def dispatch(self, request, *args, **kwargs):
        if "error" in request.GET or "code" not in request.GET:
            # Distinguish cancel from error
            auth_error = request.GET.get("error", None)
            if auth_error == self.adapter.login_cancelled_error:
                error = AuthError.CANCELLED
            else:
                error = AuthError.UNKNOWN
            return render_authentication_error(
                request, self.adapter.provider_id, error=error
            )
        app = self.adapter.get_provider().get_app(self.request)
        client = self.get_client(request, app)
        try:
            access_token = client.get_access_token(request.GET["code"])
            token = self.adapter.parse_token(access_token)
            token.app = app
            login = self.adapter.complete_login(
                request, app, token, response=access_token
            )
            login.token = token
            if "installation_id" in request.GET and "setup_action" in request.GET:
                # skip state if in installation mode
                pass
            elif self.adapter.supports_state:
                login.state = SocialLogin.verify_and_unstash_state(
                    request, get_request_param(request, "state")
                )
            else:
                login.state = SocialLogin.unstash_state(request)
            return complete_social_login(request, login)
        except (
            PermissionDenied,
            OAuth2Error,
            RequestException,
            ProviderException,
        ) as exc:
            return render_authentication_error(
                request, self.adapter.provider_id, exception=exc
            )


oauth2_login = OAuth2LoginView.adapter_view(GitHubAppOAuth2Adapter)
oauth2_callback = GitHubAppCallbackView.adapter_view(GitHubAppOAuth2Adapter)
