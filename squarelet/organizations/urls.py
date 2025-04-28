# Django
from django.urls import path

# Local
from . import views

app_name = "organizations"
urlpatterns = [
    path("", view=views.List.as_view(), name="list"),
    path("autocomplete", views.autocomplete, name="autocomplete"),
    path("~create", view=views.Create.as_view(), name="create"),
    path("~stripe_webhook/", view=views.stripe_webhook, name="stripe-webhook"),
    path("~charge/<int:pk>/", view=views.ChargeDetail.as_view(), name="charge"),
    path(
        "~charge-pdf/<int:pk>/", view=views.PDFChargeDetail.as_view(), name="charge-pdf"
    ),
    path(
        "<slug:slug>/payment/", view=views.UpdateSubscription.as_view(), name="payment"
    ),
    path("<slug:slug>/update/", view=views.Update.as_view(), name="update"),
    path(
        "<slug:slug>/manage-members/",
        view=views.ManageMembers.as_view(),
        name="manage-members",
    ),
    path(
        "<slug:slug>/manage-domains/",
        view=views.ManageDomains.as_view(),
        name="manage-domains",
    ),
    path("<slug:slug>/", view=views.Detail.as_view(), name="detail"),
    path(
        "<uuid:uuid>/invitation/",
        view=views.InvitationAccept.as_view(),
        name="invitation",
    ),
]
