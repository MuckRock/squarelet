"""Misc database utilities"""

# Django
from django.db.models import Func
from django.db.models.expressions import Value


class Interval(Func):
    """PostgreSQL interval type"""

    # pylint: disable=abstract-method

    template = "interval %(expressions)s"

    def __init__(self, expression, **extra):
        super().__init__(Value(expression), **extra)
