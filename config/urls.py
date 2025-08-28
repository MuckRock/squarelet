# Django
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.views import defaults as default_views
from django.views.generic import TemplateView

# Third Party
from allauth.account.decorators import secure_admin_login
from rest_framework_nested import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

# Squarelet
from squarelet.core.views import HomeView, SelectPlanView
from squarelet.oidc.views import OIDCRedirectURIUpdater, token_view
from squarelet.organizations.fe_api.viewsets import (
    InvitationViewSet as FEInvitationViewSet,
    OrganizationViewSet as FEOrganizationViewSet,
)
from squarelet.organizations.viewsets import ChargeViewSet, OrganizationViewSet
from squarelet.users.fe_api.viewsets import UserViewSet as FEUserViewSet
from squarelet.users.views import LoginView, SignupView, UserOnboardingView
from squarelet.users.viewsets import (
    RefreshTokenViewSet,
    UrlAuthTokenViewSet,
    UserViewSet,
)

admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)

router = routers.DefaultRouter()
router.register("users", UserViewSet)
router.register("url_auth_tokens", UrlAuthTokenViewSet, basename="url_auth_token")
router.register("refresh_tokens", RefreshTokenViewSet, basename="refresh_token")
router.register("organizations", OrganizationViewSet)
router.register("charges", ChargeViewSet)


fe_api_router = routers.DefaultRouter()
fe_api_router.register(
    r"organizations", FEOrganizationViewSet, basename="fe-organizations"
)
fe_api_router.register(r"invitations", FEInvitationViewSet, basename="fe-invitations")
fe_api_router.register(r"users", FEUserViewSet, basename="fe-users")


def redirect_erh(request, path=""):
    return redirect(
        "https://www.muckrock.com/project/elections-2024-1169/", permanent=True
    )


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("selectplan/", SelectPlanView.as_view(), name="select_plan"),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("squarelet.users.urls", namespace="users")),
    path(
        "organizations/",
        include("squarelet.organizations.urls", namespace="organizations"),
    ),
    # override the accounts login with our version
    re_path("accounts/login/$", LoginView.as_view(), name="account_login"),
    re_path(
        "accounts/onboard/$", UserOnboardingView.as_view(), name="account_onboarding"
    ),
    path("accounts/signup/", SignupView.as_view(), name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
    path("api/", include(router.urls)),
    path("fe_api/", include((fe_api_router.urls, "fe_api"), namespace="fe_api")),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("openid/", include("oidc_provider.urls", namespace="oidc_provider")),
    path("openid/jwt", token_view, name="oidc_jwt"),
    path("hijack/", include("hijack.urls", namespace="hijack")),
    re_path(r"^robots\.txt", include("robots.urls")),
    re_path(
        r"^election-hub/(?P<path>.*)?$",
        redirect_erh,
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]

# Conditionally add the API endpoint based on the environment
if settings.ENV == "staging" or settings.ENV == "dev":
    urlpatterns.append(
        path(
            "api/clients/<int:client_id>/redirect_uris/",
            OIDCRedirectURIUpdater.as_view(),
            name="oidc_redirect_uri_updater",
        )
    )

if "debug_toolbar" in settings.INSTALLED_APPS:
    # Third Party
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
