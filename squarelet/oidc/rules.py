# pylint: disable=invalid-unary-operand-type

# Third Party
from rules import add_perm, is_staff, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj


@predicate
@skip_if_not_obj
def is_owner(user, client):
    return user == client.owner


add_perm("oidc_provider.view_client", is_staff)
add_perm("oidc_provider.add_client", is_staff)
add_perm("oidc_provider.change_client", is_staff)
add_perm("oidc_provider.delete_client", is_staff)
