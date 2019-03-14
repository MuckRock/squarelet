# Django
from django import template

# Squarelet
from squarelet.organizations.models import Plan

register = template.Library()


@register.simple_tag
def planjson():
    plan_info = {
        p["slug"]: p
        for p in Plan.objects.values(
            "pk", "slug", "base_price", "price_per_user", "minimum_users"
        )
    }
    return plan_info
