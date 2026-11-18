# Django
from django import template

register = template.Library()


@register.simple_tag
def progress_bar(value, max_value):
    if value >= max_value:
        return "danger"
    if value >= max_value * 0.9:
        return "caution"
    return ""
