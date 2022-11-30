# Django
from django.urls import path

# Squarelet
from squarelet.organizations.views import IndividualUpdateSubscription

# Local
from . import views

app_name = "users"
urlpatterns = [
    # path("", view=views.UserListView.as_view(), name="list"),
    path("~redirect/", view=views.UserRedirectView.as_view(), name="redirect"),
    path("~update/", view=views.UserUpdateView.as_view(), name="update"),
    path("~payment/", view=IndividualUpdateSubscription.as_view(), name="payment"),
    path("~receipts/", view=views.Receipts.as_view(), name="receipts"),
    path("~mailgun/", view=views.mailgun_webhook, name="mailgun"),
    path("<str:username>/", view=views.UserDetailView.as_view(), name="detail"),
]
