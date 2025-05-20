# Third Party
from rest_framework.permissions import BasePermission


class CanAcceptOrRejectInvitation(BasePermission):
    """
    Invites can only be accepted or rejected
    - If the user is the subject of the invitation and it isn't a request to join.
      We don't want users accepting their own request to joins.


    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        user_verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )
        is_target = obj.email in user_verified_emails and not obj.request
        is_admin = obj.organization.has_admin(user)
        is_request = obj.request

        return (is_target) or (is_admin and is_request)


class CanWithdrawInvitation(BasePermission):
    """
    Allows withdrawal if:
    - It's a join request and the requesting user is the one revoking.
    - It's an admin invitation and the user is an admin
      of the organization the invitation pertains to.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        return (obj.request and obj.user == user) or (
            not obj.request and obj.organization.has_admin(user)
        )
