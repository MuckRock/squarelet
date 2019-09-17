# Django
from django.utils.safestring import mark_safe

# Standard Library
import json


def mixpanel_event(request, event, props=None, **kwargs):
    """Add an event to the session to be sent via javascript on the next page
    load
    """
    if props is None:
        props = {}
    if "mp_events" in request.session:
        request.session["mp_events"].append((event, mark_safe(json.dumps(props))))
    else:
        request.session["mp_events"] = [(event, mark_safe(json.dumps(props)))]
    if kwargs.get("signup"):
        request.session["mp_alias"] = True
    if kwargs.get("charge"):
        request.session["mp_charge"] = kwargs["charge"]
