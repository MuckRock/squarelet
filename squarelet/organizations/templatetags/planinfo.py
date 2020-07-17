# Django
from django import template
from django.utils.html import json_script

# Squarelet
from squarelet.organizations.choices import StripeAccounts

# Local
from ..models import Plan

register = template.Library()


@register.simple_tag
def planinfo(organization=None, field="pk"):
    if organization:
        plans = Plan.objects.choices(organization, StripeAccounts.muckrock)
    else:
        plans = Plan.objects.filter(public=True)
    plan_info = {
        p[field]: p
        for p in plans.values(
            "pk", "slug", "base_price", "price_per_user", "minimum_users", "annual"
        )
    }
    # add in free
    free_info = {
        "pk": "",
        "slug": "free",
        "base_price": 0,
        "price_per_user": 0,
        "minimum_users": 1,
        "annual": False,
    }
    plan_info[free_info[field]] = free_info
    return json_script(plan_info, "_id-planInfo")
