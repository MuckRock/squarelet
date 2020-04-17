# Django
from django.urls import path

from squarelet.email_helpers import views

app_name = "email_helpers"
urlpatterns = [
    path("add/", views.AddEmailView.as_view(), name="add_email"),
    path("remove/", views.RemoveEmailView.as_view(), name="add_email"),
    path("primary/", views.PrimaryEmailView.as_view(), name="add_email"),
    path("send/", views.SendEmailView.as_view(), name="add_email"),

    # xxx TODO: I think we need a GET ./ request in here that returns all email addresses for a logged-in user?
    # otherwise, how can we provide a list in PressPass that allows someone to resend confirmation, make primary
    # or remove an email address from his/her account?
]
