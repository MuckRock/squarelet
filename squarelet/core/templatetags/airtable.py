# Django
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

# Standard Library
from urllib.parse import urlencode

register = template.Library()


@register.simple_tag
def airtable_form_url(base_url, **kwargs):
    """
    Generate an Airtable form URL with prefilled fields.
    """
    if not kwargs:
        return base_url

    # Convert kwargs to Airtable's prefill format
    prefill_params = {}
    for key, value in kwargs.items():
        prefill_key = f"prefill_{key}"
        if isinstance(value, list):
            # Airtable expects lists to be formatted as comma-separated strings
            prefill_params[prefill_key] = ",".join(map(str, value))
        elif value is not None:
            prefill_params[prefill_key] = str(value)
    if prefill_params:
        # Encode the parameters and append to the base URL
        query_string = urlencode(prefill_params)
        return mark_safe(f"{base_url}?{query_string}")

    return base_url


@register.simple_tag(takes_context=True)
def airtable_verification_url(context, organization=None):
    """Generate a verification form URL with a user and an organization."""
    user = context["request"].user
    user_url = context["request"].build_absolute_uri(user.get_absolute_url())

    prefill_data = {
        "Your Name": user.get_full_name() or user.username,
        "Email address on your account": user.email,
        "MR User Account URL": user_url,
    }
    if organization:
        org_urls = organization.urls.all() if organization else []
        organization_url = context["request"].build_absolute_uri(
            organization.get_absolute_url()
        )
        prefill_data.update(
            {
                "Organization or Project Name": organization.name,
                "Organization URL": org_urls[0].url if org_urls else "",
                "MR Organization Account URL": organization_url,
            }
        )
    filtered_data = {k: v for k, v in prefill_data.items() if v}

    return airtable_form_url(settings.VERIFICATION_FORM_URL, **filtered_data)
