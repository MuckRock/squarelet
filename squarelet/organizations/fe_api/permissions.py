# Third Party
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

# Squarelet
from squarelet.organizations.models import Organization


class CanAcceptInvitation(BasePermission):
    """
    Accepting is allowed if:
    - The user is the invitee (verified email) and it's NOT a join request (i.e., an admin sent the invite).
    - The user is an admin and the invitation is a join request.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )

        is_invitee = obj.email in verified_emails
        is_admin = obj.organization.has_admin(user)
        is_request = obj.request

        return (is_invitee and not is_request) or (is_admin and is_request)


class CanRejectInvitation(BasePermission):
    """
    Rejecting is allowed if:
    - Join request (request=True): only an admin can reject.
    - Admin invitation (request=False): the invitee (email match) or an admin can reject.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        is_admin = obj.organization.has_admin(user)

        if obj.request:
            return is_admin

        verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )
        is_invitee = obj.email in verified_emails
        return is_invitee or is_admin


class CanWithdrawInvitation(BasePermission):
    """
    Withdrawing is allowed if:
    - Join request (request=True): only the requester can withdraw.
    - Admin invitation (request=False): only an admin can withdraw.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        is_requester = obj.user == user
        is_admin = obj.organization.has_admin(user)

        if obj.request:
            return is_requester
        return is_admin


class CanResendInvitation(BasePermission):
    """
    Resending is allowed only if:
    - The user is an admin of the organization that sent the invitation.
    """

    def has_object_permission(self, request, view, obj):
        return obj.organization.has_admin(request.user)


class CanCreateInvitation(BasePermission):
    """
    Allows user to create an invitation only if the user is an admin of the target organization.
    """

    def has_permission(self, request, view):
        if request.method != "POST":
            # Allow GET
            return True

        org_id = request.data.get("organization")
        if not org_id:
            # No org yet, allow form rendering
            return True

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            raise PermissionDenied("Organization not found.")

        return org.has_admin(request.user)
