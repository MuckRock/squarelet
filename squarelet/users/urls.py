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
    path(
        "<str:username>/invitations/",
        view=views.UserInvitationsView.as_view(),
        name="invitations",
    ),
    path(
        "<str:username>/requests/",
        view=views.UserRequestsView.as_view(),
        name="requests",
    ),
    path(
        "<str:username>/subscriptions/",
        view=views.ManageSubscriptions.as_view(),
        name="subscriptions",
    ),
    path(
        "<str:username>/cancel/<int:pk>/",
        view=views.CancelSubscription.as_view(),
        name="cancel-subscription",
    ),
    path(
        "<str:username>/update-frequency/<int:pk>/",
        view=views.UpdateSubscriptionFrequency.as_view(),
        name="update-frequency",
    ),
    path(
        "<str:username>/receipt-email/",
        view=views.UpdateReceiptEmail.as_view(),
        name="update-receipt-email",
    ),
    path("<str:username>/card/", view=views.UpdateCard.as_view(), name="update-card"),
    path(
        "<str:username>/payments/", view=views.PaymentsList.as_view(), name="payments"
    ),
]
