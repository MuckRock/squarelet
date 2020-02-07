# pylint: disable=unused-argument, invalid-unary-operand-type

# Third Party
from rules import add_perm, always_deny, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj


@predicate
@skip_if_not_obj
def is_member(user, subscription):
    return subscription.organization.has_member(user)


@predicate
@skip_if_not_obj
def is_admin(user, subscription):
    return subscription.organization.has_admin(user)


add_perm("organizations.view_subscription", is_authenticated & is_member)
add_perm("organizations.add_subscription", is_authenticated)
add_perm("organizations.change_subscription", is_authenticated & is_admin)
add_perm("organizations.delete_subscription", is_authenticated & is_admin)
