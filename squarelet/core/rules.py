# Standard Library
# Django
from django.contrib.auth import load_backend

from functools import wraps

# Third Party
from rules import add_perm, predicate


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


def has_db_perm(perm):
    @predicate(f"has_db_perm:{perm}")
    def inner(user):
        # we want to directly check the model backend for a permissions to avoid
        # infinite recursion
        backend = load_backend("django.contrib.auth.backends.ModelBackend")
        return backend.has_perm(user, perm)

    return inner


def add_perm_with_db_check(perm, pred):
    """
    This will give permissions if the `pred` passes or if
    the permission has been explicitly set
    """
    add_perm(perm, pred | has_db_perm(perm))
