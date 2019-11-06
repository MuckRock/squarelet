# pylint: disable=unused-argument, invalid-unary-operand-type

# Standard Library
from functools import wraps

# Third Party
from rules import add_perm, always_deny, is_authenticated, predicate


def skip_if_not_obj(func):
    """Decorator for predicates
    Skip the predicate if obj is None"""

    @wraps(func)
    def inner(user, obj):
        if obj is None:
            return None
        else:
            return func(user, obj)

    return inner


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

add_perm("organizations.view_organization", is_public | (is_authenticated & is_member))
add_perm("organizations.add_organization", is_authenticated)
add_perm("organizations.change_organization", is_authenticated & is_admin)
add_perm("organizations.delete_organization", always_deny)
