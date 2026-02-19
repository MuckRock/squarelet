# pylint: disable=unused-argument, invalid-unary-operand-type

# Third Party
from rules import add_perm, always_deny, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj, add_perm_with_db_check


@predicate
@skip_if_not_obj
def is_private(user, organization):
    return organization.private


@predicate
@skip_if_not_obj
def is_member(user, organization):
    return organization.has_member(user)


@predicate
@skip_if_not_obj
def is_admin(user, organization):
    return organization.has_admin(user)


is_public = ~is_private

add_perm("organizations.add_organization", is_authenticated)
add_perm("organizations.view_organization", is_public | is_member)
add_perm("organizations.delete_organization", always_deny)
add_perm_with_db_check("organizations.change_organization", is_admin)
add_perm_with_db_check("organizations.can_manage_members", is_admin)
add_perm_with_db_check("organizations.can_view_members", is_member)
add_perm_with_db_check("organizations.can_view_subscription", is_member)
add_perm_with_db_check("organizations.can_edit_subscription", is_admin)
add_perm_with_db_check("organizations.can_view_charge", is_admin)
