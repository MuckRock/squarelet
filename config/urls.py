# Django
from django.conf import settings
from django.conf.urls import url
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views import defaults as default_views
from django.views.generic import TemplateView

# Third Party
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework_nested import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

# Squarelet
from squarelet.core.views import HomeView
from squarelet.oidc.viewsets import ClientViewSet
from squarelet.organizations.viewsets import (
    ChargeViewSet,
    OrganizationViewSet,
    PressPassInvitationViewSet,
    PressPassMembershipViewSet,
    PressPassNestedInvitationViewSet,
    PressPassOrganizationViewSet,
    PressPassPlanViewSet,
)
from squarelet.users.views import LoginView
from squarelet.users.viewsets import (
    PressPassUserViewSet,
    UrlAuthTokenViewSet,
    UserViewSet,
)

SchemaView = get_schema_view(
    openapi.Info(
        title="Squarelet API",
        default_version="v1",
        description="API for Muckrock Accounts and PressPass",
        terms_of_service="https://www.muckrock.com/tos/",
        contact=openapi.Contact(email="mitch@muckrock.com"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

router = routers.DefaultRouter()
router.register("users", UserViewSet)
router.register("url_auth_tokens", UrlAuthTokenViewSet, base_name="url_auth_token")
router.register("organizations", OrganizationViewSet)
router.register("charges", ChargeViewSet)

presspass_router = routers.DefaultRouter()
presspass_router.register("clients", ClientViewSet)
presspass_router.register("users", PressPassUserViewSet)
presspass_router.register("organizations", PressPassOrganizationViewSet)
presspass_router.register("invitations", PressPassInvitationViewSet)
presspass_router.register("plans", PressPassPlanViewSet)

organization_router = routers.NestedDefaultRouter(
    presspass_router, "organizations", lookup="organization"
)
organization_router.register("memberships", PressPassMembershipViewSet)
organization_router.register("invitations", PressPassNestedInvitationViewSet)

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
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
    url("accounts/login/$", LoginView.as_view(), name="account_login"),
    path("accounts/", include("allauth.urls")),
    path("api/", include(router.urls)),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("pp-api/", include(presspass_router.urls)),
    path("pp-api/", include(organization_router.urls)),
    # Swagger
    path("swagger<format>", SchemaView.without_ui(cache_timeout=0), name="schema-json"),
    path(
        "swagger/",
        SchemaView.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("csrf/", include("squarelet.csrf.urls")),
    path("authstatus/", include("squarelet.authstatus.urls")),
    path("openid/", include("oidc_provider.urls", namespace="oidc_provider")),
    path("hijack/", include("hijack.urls", namespace="hijack")),
    path("rest-auth/", include("rest_auth.urls")),
    path("rest-auth/registration/", include("rest_auth.registration.urls")),
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
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
