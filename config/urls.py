# Django
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views import defaults as default_views
from django.views.generic import TemplateView

# Third Party
from rest_framework import permissions
from rest_framework_nested import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

# Squarelet
from squarelet.core.views import ERHLandingView, HomeView
from squarelet.oidc.views import token_view
from squarelet.organizations.viewsets import ChargeViewSet, OrganizationViewSet
from squarelet.users.views import LoginView
from squarelet.users.viewsets import (
    RefreshTokenViewSet,
    UrlAuthTokenViewSet,
    UserViewSet,
)

router = routers.DefaultRouter()
router.register("users", UserViewSet)
router.register("url_auth_tokens", UrlAuthTokenViewSet, basename="url_auth_token")
router.register("refresh_tokens", RefreshTokenViewSet, basename="refresh_token")
router.register("organizations", OrganizationViewSet)
router.register("charges", ChargeViewSet)


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("election-hub/", ERHLandingView.as_view(), name="erh_landing"),
    path(
        "selectplan/",
        TemplateView.as_view(template_name="pages/selectplan.html"),
        name="select_plan",
    ),
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
    path("accounts/", include("allauth.urls")),
    path("api/", include(router.urls)),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("openid/", include("oidc_provider.urls", namespace="oidc_provider")),
    path("openid/jwt", token_view, name="oidc_jwt"),
    path("hijack/", include("hijack.urls", namespace="hijack")),
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
if "debug_toolbar" in settings.INSTALLED_APPS:
    # Third Party
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
