# Django
from django import template

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
    intent = "muckrock"
    if "intent" in context.request.GET:
        intent = context.request.GET["intent"].lower().strip()

    if intent == "documentcloud":
        intent_service = DOCUMENTCLOUD_SERVICE
        intent_asset = DOCUMENTCLOUD_ASSET
    elif intent == "foiamachine":
        intent_service = FOIAMACHINE_SERVICE
        intent_asset = FOIAMACHINE_ASSET
    elif intent == "quackbot":
        intent_service = QUACKBOT_SERVICE
        intent_asset = QUACKBOT_ASSET
    else:
        # default to MuckRock
        intent_service = MUCKROCK_SERVICE
        intent_asset = MUCKROCK_ASSET

    other_services = ALL_SERVICES[:]
    other_services.remove(intent_service)
    other_assets = ALL_ASSETS[:]
    other_assets.remove(intent_asset)

    return {
        "header": header,
        "message": message,
        "intent_service": intent_service,
        "intent_asset": intent_asset,
        "other_service_1": other_services[0],
        "other_service_2": other_services[1],
        "other_service_3": other_services[2],
        "other_asset_1": other_assets[0],
        "other_asset_2": other_assets[1],
        "other_asset_3": other_assets[2],
    }
