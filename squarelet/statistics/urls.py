# Django
from django.urls import path

# Local
from . import views

app_name = "statistics"
urlpatterns = [
    path("kpis/", view=views.KPIDashboardView.as_view(), name="kpis"),
]
