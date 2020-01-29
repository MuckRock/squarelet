# pylint: disable=unused-argument, invalid-unary-operand-type

# Third Party
from rules import add_perm, always_allow, always_deny, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj
from squarelet.organizations.rules import organizations


@predicate
@skip_if_not_obj
def is_request(user, invitation):
    return invitation.request


@predicate
@skip_if_not_obj
def is_admin(user, invitation):
    return organizations.is_admin(user, invitation.organization)


add_perm("organizations.view_invitation", always_allow)
add_perm("organizations.add_invitation", is_authenticated)
add_perm(
    "organizations.change_invitation",
    (is_request & is_admin) | (~is_request & is_authenticated),
)
add_perm("organizations.delete_invitation", always_deny)
