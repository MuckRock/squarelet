# Django
from django import template
from django.utils.translation import ugettext_lazy as _

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

# Services and assets in order of display priority
ALL_SERVICES = [
    MUCKROCK_SERVICE,
    DOCUMENTCLOUD_SERVICE,
    FOIAMACHINE_SERVICE,
    QUACKBOT_SERVICE,
]
ALL_ASSETS = [MUCKROCK_ASSET, DOCUMENTCLOUD_ASSET, FOIAMACHINE_ASSET, QUACKBOT_ASSET]


@register.inclusion_tag("templatetags/intent.html", takes_context=True)
def handleintent(context, header, message):
    if "intent" in context.request.GET:
        intent = context.request.GET["intent"].lower().strip()
    else:
        intent = "muckrock"

    intent_lookup = {
        "documentcloud": (DOCUMENTCLOUD_SERVICE, DOCUMENTCLOUD_ASSET),
        "foiamachine": (FOIAMACHINE_SERVICE, FOIAMACHINE_ASSET),
        "quackbot": (QUACKBOT_SERVICE, QUACKBOT_ASSET),
        "muckrock": (MUCKROCK_SERVICE, MUCKROCK_ASSET),
    }

    # default to 'muckrock'
    intent_service, intent_asset = intent_lookup.get(intent, intent_lookup["muckrock"])

    other_services = [s for s in ALL_SERVICES if s != intent_service]
    other_assets = [a for a in ALL_ASSETS if a != intent_asset]

    service_message = _("{}, and {}").format(
        ", ".join(other_services[:-1]), other_services[-1]
    )

    return {
        "header": header,
        "message": f"{message} {service_message}",
        "intent_service": intent_service,
        "intent_asset": intent_asset,
        "other_assets": other_assets,
    }
