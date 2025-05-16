# Django
from django import template

# Standard Library
from urllib.parse import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def pass_query(context, *args, **kwargs):
    """
    Creates a URL query string based on current request's query parameters.

    Returns: a formatted query string starting with '?' or empty string if no parameters

    Usage:

    {% pass_query %}  # Passes all current query parameters
    {% pass_query intent='squarelet' %}  # Overrides or adds intent parameter
    {% pass_query plan=None %}  # Removes plan parameter
    """
    request = context.get("request")
    if not request:
        return ""

    # Start with current GET parameters
    params = request.GET.dict()

    # Update with any explicitly provided parameters
    for key, value in kwargs.items():
        if value is None and key in params:
            # Remove the parameter if None is specified
            del params[key]
        else:
            params[key] = value

    # Ensure intent exists with default value if not provided
    if "intent" not in params:
        params["intent"] = "squarelet"

    # Convert to query string
    if params:
        return "?" + urlencode(params)
    return ""
