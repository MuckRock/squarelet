# Django
from django import template

register = template.Library()


@register.filter
def has_verified_email(user):
    """Return True if the user has at least one verified email address."""
    if not user or not user.is_authenticated:
        return False
    return user.emailaddress_set.filter(verified=True).exists()
