# Third Party
from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns

# Local
from .provider import GitHubAppProvider

urlpatterns = default_urlpatterns(GitHubAppProvider)
