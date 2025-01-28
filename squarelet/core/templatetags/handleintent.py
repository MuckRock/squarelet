# Django
from django import template
from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Standard Library
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse

from squarelet.services.models import Service

register = template.Library()


@register.inclusion_tag("templatetags/services_list.html")
def services_list():
    providers = (
        Service.objects.all()
        .order_by("-provider_name__exact", "name")
        .extra(
            select={"provider_name_is_muckrock": "provider_name = 'MuckRock'"},
            order_by=["-provider_name_is_muckrock", "name"],
        )
    )
    return {"service_providers": providers}


@register.inclusion_tag("templatetags/sign_in_message.html", takes_context=True)
def sign_in_message(context):
    no_match = {
        "header": "Sign in to your MuckRock account to manage your organizations and plans",
        "service": None,
    }

    # Find the service provider based on the intent
    intent = context.request.GET.get("intent")
    if not intent:
        next_ = context.request.GET.get("next")
        if next_:
            url = urlparse(next_)
            params = parse_qs(url.query)
            intent = params.get("intent", [None])[0]
    if not intent:
        return no_match
    intent = intent.lower().strip()
    try:
        service = Service.objects.get(slug=intent)
    except Service.DoesNotExist:
        return no_match

    return {
        "header": "Sign in with your MuckRock account",
        "service": service,
    }
