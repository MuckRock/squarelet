# Django
from django import template
from django.utils.translation import gettext_lazy as _

# Standard Library
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse

register = template.Library()

# Service names and assets pointing to their logos
MUCKROCK_SERVICE = "MuckRock"
MUCKROCK_ASSET = "assets/muckrock.svg"

DOCUMENTCLOUD_SERVICE = "DocumentCloud"
DOCUMENTCLOUD_ASSET = "assets/documentcloud.svg"

FOIAMACHINE_SERVICE = "FOIA Machine"
FOIAMACHINE_ASSET = "assets/foiamachine.svg"

QUACKBOT_SERVICE = "Quackbot"
QUACKBOT_ASSET = "assets/quackbot.svg"


@register.inclusion_tag("templatetags/intent.html", takes_context=True)
def handleintent(context, header, message):
    intent = context.request.GET.get("intent")
    if not intent:
        next_ = context.request.GET.get("next")
        if next_:
            url = urlparse(next_)
            params = parse_qs(url.query)
            intent = params.get("intent", [None])[0]
    if not intent:
        intent = "muckrock"
    intent = intent.lower().strip()

    intent_lookup = OrderedDict(
        [
            ("muckrock", (MUCKROCK_SERVICE, MUCKROCK_ASSET)),
            ("documentcloud", (DOCUMENTCLOUD_SERVICE, DOCUMENTCLOUD_ASSET)),
            ("foiamachine", (FOIAMACHINE_SERVICE, FOIAMACHINE_ASSET)),
            # ("quackbot", (QUACKBOT_SERVICE, QUACKBOT_ASSET)),
        ]
    )

    # default to 'muckrock'
    intent_service, intent_asset = intent_lookup.get(intent, intent_lookup["muckrock"])

    other_services = [s for s, a in intent_lookup.values() if s != intent_service]
    other_assets = [a for s, a in intent_lookup.values() if a != intent_asset]

    if len(other_services) == 1:
        service_message = other_services[0]
    else:
        service_message = _("{} and {}").format(
            ", ".join(other_services[:-1]), other_services[-1]
        )

    return {
        "header": header,
        "message": f"{message} {service_message}",
        "intent_service": intent_service,
        "intent_asset": intent_asset,
        "other_assets": other_assets,
    }
