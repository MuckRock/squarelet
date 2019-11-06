# Django
from django.urls import path

# Local
from . import views

app_name = "authstatus"
urlpatterns = [
    path("check/", view=views.check, name="check"),
]
