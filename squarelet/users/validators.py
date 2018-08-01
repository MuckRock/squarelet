"""Validators for the user models"""

# Django
from django.core import validators
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

# Standard Library
import re


@deconstructible
class UsernameValidator(validators.RegexValidator):
    """The standard username validator, except disallowing @ symbols"""

    regex = r"^[\w.-]+$"
    message = _(
        "Enter a valid username. This value may contain only English letters, "
        "numbers, and ./-/_ characters."
    )
    flags = re.ASCII
