# Standard Library
from functools import wraps


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


def deny_if_not_obj(func):
    """Decorator for predicates
    Deny the predicate if obj is None"""

    @wraps(func)
    def inner(user, obj):
        if obj is None:
            return False
        else:
            return func(user, obj)

    return inner
