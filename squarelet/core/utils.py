# Standard Library
import json
import os.path


def mixpanel_event(request, event, props=None, **kwargs):
    """Add an event to the session to be sent via javascript on the next page
    load
    """
    if props is None:
        props = {}
    if "mp_events" in request.session:
        request.session["mp_events"].append((event, json.dumps(props)))
    else:
        request.session["mp_events"] = [(event, json.dumps(props))]
    if kwargs.get("signup"):
        request.session["mp_alias"] = True
    if kwargs.get("charge"):
        request.session["mp_charge"] = kwargs["charge"]


def file_path(base, _instance, filename):
    """Create a file path that fits within the 100 character limit"""
    # 100 character is the default character limit, subtract 8 to allow for unique
    # suffixes if necessary
    path_limit = 100 - 8

    path = os.path.join(base, filename)
    if len(path) <= path_limit:
        return path
    else:
        file_base, file_ext = os.path.splitext(filename)
        # file base must be no longer then the limit, minus the length of the base
        # directory, the file extensions, plus one for the '/'
        file_base = file_base[: path_limit - (len(base) + len(file_ext) + 1)]
        return os.path.join(base, f"{file_base}{file_ext}")
