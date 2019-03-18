# Django
from django import template
from django.utils.html import json_script

# Local
from ..models import Plan

register = template.Library()


@register.simple_tag
def planinfo(field="pk"):
    plan_info = {
        p[field]: p
        for p in Plan.objects.values(
            "pk", "slug", "base_price", "price_per_user", "minimum_users"
        )
    }
    return json_script(plan_info, "_id-planInfo")
