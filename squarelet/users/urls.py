# Django
from django.urls import path

# Squarelet
from squarelet.organizations.views import IndividualReceipts, IndividualUpdate

# Local
from . import views

app_name = "users"
urlpatterns = [
    path("", view=views.UserListView.as_view(), name="list"),
    path("~redirect/", view=views.UserRedirectView.as_view(), name="redirect"),
    path("~update/", view=views.UserUpdateView.as_view(), name="update"),
    path("~payment/", view=IndividualUpdate.as_view(), name="payment"),
    path("~receipts/", view=IndividualReceipts.as_view(), name="receipts"),
<<<<<<< HEAD
=======
    path("~mailgun/", view=views.mailgun_webhook, name="mailgun"),
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c
    path("<str:username>/", view=views.UserDetailView.as_view(), name="detail"),
]
