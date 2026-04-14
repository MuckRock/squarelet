# Django
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

ICONS_DIR = settings.ROOT_DIR.path("frontend", "icons")


@register.simple_tag
def icon(name):
    """Render an inline SVG icon from frontend/icons/{name}.svg"""
    path = ICONS_DIR.path(f"{name}.svg")
    with open(str(path), encoding="utf-8") as f:
        return mark_safe(f.read())
