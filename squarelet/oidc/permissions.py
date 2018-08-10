
# Third Party
from rest_framework import permissions


class ScopePermission(permissions.BasePermission):
    """Require scopes for permission"""

    def has_permission(self, request, view):
        scopes = set(getattr(view, "scopes", []))
        read_scopes = set(getattr(view, "read_scopes", scopes))
        write_scopes = set(getattr(view, "write_scopes", scopes))
        if not hasattr(request, "auth") or not request.auth:
            return False

        auth_scopes = set(request.auth.scope)

        if request.method in permissions.SAFE_METHODS:
            return read_scopes and read_scopes <= auth_scopes
        else:
            return write_scopes and write_scopes <= auth_scopes
