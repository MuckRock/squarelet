# Django
from django.urls import path

from . import views

app_name = "glomar"

urlpatterns = [
    path("", views.GlomarDashboardView.as_view(), name="dashboard"),
    path(
        "users/<slug:username>/",
        views.GlomarUserDetailView.as_view(),
        name="user_detail",
    ),
    path(
        "organizations/<slug:slug>/",
        views.GlomarOrganizationDetailView.as_view(),
        name="organization_detail",
    ),
]
