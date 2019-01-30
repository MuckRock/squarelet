# Django
from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def avatar(profile_or_org, size=45):
    return format_html(
        '<div class="_cls-avatar"><img width="{size}" height="{size}" src="{src}">'
        "</div>",
        size=size,
        src=profile_or_org.avatar_url,
    )
