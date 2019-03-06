# Django
from django import template

register = template.Library()


@register.simple_tag
def autologin(url, user):
    if not user or not user.is_authenticated:
        return url
    else:
        return user.wrap_url(url)
