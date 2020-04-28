# pylint: disable=unused-argument

# Third Party
from rules import add_perm, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj


@predicate
@skip_if_not_obj
def is_owner(user, entitlement):
    return user == entitlement.client.owner


@predicate
@skip_if_not_obj
def is_public(user, entitlement):
    return entitlement.public


add_perm("organizations.view_entitlement", is_public | (is_authenticated & is_owner))
add_perm("organizations.add_entitlement", is_authenticated)
add_perm("organizations.change_entitlement", is_authenticated & is_owner)
add_perm("organizations.delete_entitlement", is_authenticated & is_owner)
