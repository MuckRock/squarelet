# Third Party
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
    Rejecting (or withdrawing) is allowed if:
    - The user is an admin of the organization.
    - The user is the requester of a join request.
    - The user is the invitee of an admin invite (email match).
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        verified_emails = user.emailaddress_set.filter(verified=True).values_list(
            "email", flat=True
        )

        is_invitee = obj.email in verified_emails  # receiving an invite
        is_requester = obj.user == user  # submitted a join request
        is_admin = obj.organization.has_admin(user)

        return is_admin or is_requester or is_invitee


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
