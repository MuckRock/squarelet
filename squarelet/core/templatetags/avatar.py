# Django
from django import template
from django.utils.html import format_html

# Squarelet
from squarelet.users.models import User

register = template.Library()


@register.simple_tag
def avatar(profile_or_org, size=45):
    if profile_or_org is not None:
        src = profile_or_org.avatar_url
    else:
        src = User.default_avatar
    return format_html(
        '<div class="_cls-avatar"><img width="{size}" height="{size}" src="{src}">'
        "</div>",
        size=size,
        src=src,
    )
