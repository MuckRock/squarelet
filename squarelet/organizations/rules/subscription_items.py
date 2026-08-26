# Third Party
from rules import add_perm, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj


@predicate
@skip_if_not_obj
def is_member(user, item):
    return item.organization.has_member(user)


@predicate
@skip_if_not_obj
def is_admin(user, item):
    return item.organization.has_admin(user)


add_perm("organizations.view_subscriptionitem", is_authenticated & is_member)
add_perm("organizations.add_subscriptionitem", is_authenticated)
add_perm("organizations.change_subscriptionitem", is_authenticated & is_admin)
add_perm("organizations.delete_subscriptionitem", is_authenticated & is_admin)
