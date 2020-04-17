# Django
from django.urls import path

from squarelet.email_helpers import views

app_name = "email_helpers"
urlpatterns = [
    path("add/", views.EmailView.as_view(), name="add_email"),
]
