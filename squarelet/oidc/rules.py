# pylint: disable=invalid-unary-operand-type

# Third Party
from rules import add_perm, is_authenticated, predicate


@predicate
def is_owner(user, client):
    if client is None:
        return None
    return user == client.owner


add_perm("oidc_provider.view_client", is_authenticated & is_owner)
add_perm("oidc_provider.add_client", is_authenticated)
add_perm("oidc_provider.change_client", is_authenticated & is_owner)
add_perm("oidc_provider.delete_client", is_authenticated & is_owner)
