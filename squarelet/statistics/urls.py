# Django
from django.urls import path
from django.views.generic import RedirectView

# Local
from . import views

app_name = "statistics"
urlpatterns = [
    path("users/", view=views.UserDashboardView.as_view(), name="users"),
    path(
        "kpis/",
        view=RedirectView.as_view(pattern_name="statistics:users", permanent=True),
    ),
]
