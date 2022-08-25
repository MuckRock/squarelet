# Third Party
from rules import add_perm, always_deny, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj
from squarelet.organizations.rules import organizations


@predicate
@skip_if_not_obj
def is_public(user, membership):
    return organizations.is_public(user, membership.organization)


@predicate
@skip_if_not_obj
def is_organization(user, membership):
    return organizations.is_member(user, membership.organization)


@predicate
@skip_if_not_obj
def is_admin(user, membership):
    return organizations.is_admin(user, membership.organization)


@predicate
@skip_if_not_obj
def is_owner(user, membership):
    return user == membership.user


add_perm(
    "organizations.view_membership", is_public | (is_authenticated & is_organization)
)
add_perm("organizations.add_membership", always_deny)
add_perm("organizations.change_membership", is_authenticated & is_admin)
add_perm("organizations.delete_membership", is_authenticated & (is_owner | is_admin))
