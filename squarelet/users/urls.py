# Django
from django.urls import path

# Local
from . import views

app_name = "users"
urlpatterns = [
    # path("", view=views.UserListView.as_view(), name="list"),
    path("~mailgun/", view=views.mailgun_webhook, name="mailgun"),
    # Redirect tilde routes to current user routes
    path(
        "~redirect/",
        view=views.UserRedirectView.as_view(),
        kwargs={"target_view": "detail"},
        name="redirect",
    ),
    path(
        "~update/",
        view=views.UserRedirectView.as_view(),
        kwargs={"target_view": "update"},
        name="update_redirect",
    ),
    path(
        "~payment/",
        view=views.UserRedirectView.as_view(),
        kwargs={"target_view": "payment"},
        name="payment_redirect",
    ),
    path(
        "~receipts/",
        view=views.UserRedirectView.as_view(),
        kwargs={"target_view": "receipts"},
        name="receipts_redirect",
    ),
    # Private username-based routes with staff access
    path("<str:username>/", view=views.UserDetailView.as_view(), name="detail"),
    path("<str:username>/update/", view=views.UserUpdateView.as_view(), name="update"),
    path(
        "<str:username>/payment/", view=views.UserPaymentView.as_view(), name="payment"
    ),
    path("<str:username>/receipts/", view=views.Receipts.as_view(), name="receipts"),
]
