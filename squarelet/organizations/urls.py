# Django
from django.urls import path

# Local
from . import views

app_name = "organizations"
urlpatterns = [
    path("", view=views.List.as_view(), name="list"),
    path("autocomplete", views.Autocomplete, name="org-autocomplete"),
    path("~create", view=views.Create.as_view(), name="create"),
    path("<slug:slug>/update/", view=views.Update.as_view(), name="update"),
    path("<slug:slug>/add-member/", view=views.AddMember.as_view(), name="add-member"),
    path(
        "<slug:slug>/buy-requests/",
        view=views.BuyRequests.as_view(),
        name="buy-requests",
    ),
    path(
        "<slug:slug>/manage-members/",
        view=views.ManageMembers.as_view(),
        name="manage-members",
    ),
    path(
        "<slug:slug>/manage-invitations/",
        view=views.ManageInvitations.as_view(),
        name="manage-invitations",
    ),
    path("<slug:slug>/", view=views.Detail.as_view(), name="detail"),
    path(
        "<uuid:uuid>/invitation/",
        view=views.InvitationAccept.as_view(),
        name="invitation",
    ),
]
