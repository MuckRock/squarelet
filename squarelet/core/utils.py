# Django
from django.conf import settings

# Standard Library
import logging
import os.path
import sys
import uuid
from hashlib import md5

# Third Party
import requests
import stripe

logger = logging.getLogger(__name__)


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


def retry_on_error(errors, func, *args, **kwargs):
    """Retry a function on error"""
    max_retries = 10
    times = kwargs.pop("times", 0) + 1
    try:
        return func(*args, **kwargs)
    except errors as exc:
        if times > max_retries:
            raise exc
        logger.warning(
            "Error, retrying #%d:\n\n%s", times, exc, exc_info=sys.exc_info()
        )
        return retry_on_error(errors, func, times=times, *args, **kwargs)


def stripe_retry_on_error(func, *args, **kwargs):
    """Retry stripe API calls on connection errors"""
    if kwargs.get("idempotency_key") is True:
        kwargs["idempotency_key"] = uuid.uuid4().hex
    return retry_on_error(
        (stripe.error.APIConnectionError, stripe.error.RateLimitError),
        func,
        *args,
        **kwargs,
    )


def mailchimp_subscribe(emails, list_=settings.MAILCHIMP_LIST_DEFAULT):
    """Adds the email to the mailing list throught the MailChimp API.
    https://mailchimp.com/developer/marketing/api/lists/"""

    api_url = f"{settings.MAILCHIMP_API_ROOT}/lists/{list_}/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"apikey {settings.MAILCHIMP_API_KEY}",
    }
    data = {
        "members": [
            {
                "email_address": email,
                "status": "subscribed",
            }
            for email in emails
        ]
    }
    response = retry_on_error(
        requests.ConnectionError, requests.post, api_url, json=data, headers=headers
    )
    return response


def mailchimp_journey(email, journey):
    """Trigger a mailchimp journey for the given email address"""

    # IDs for our journeys
    journey_map = {
        "keh": (12, 68, "64f4342878"),
        "verified": (4, 72, "a34d93cbe8"),
    }
    journey_id, step_id, list_id = journey_map[journey]

    subscriber_hash = md5(email.lower().encode()).hexdigest()

    # first ensure they are in the proper audience
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"apikey {settings.MAILCHIMP_API_KEY}",
    }
    api_url = f"{settings.MAILCHIMP_API_ROOT}/lists/{list_id}/members/{subscriber_hash}"
    data = {
        "email_address": email,
        "status": "subscribed",
    }
    response = retry_on_error(
        requests.ConnectionError, requests.put, api_url, json=data, headers=headers
    )
    if response.status_code >= 400:
        logger.warning("[JOURNEY] Error adding to audience", exc_info=sys.exc_info())

    api_url = (
        f"{settings.MAILCHIMP_API_ROOT}/customer-journeys/journeys/"
        f"{journey_id}/steps/{step_id}/actions/trigger"
    )
    data = {"email_address": email}
    response = retry_on_error(
        requests.ConnectionError, requests.post, api_url, json=data, headers=headers
    )
    if response.status_code >= 400:
        logger.warning("[JOURNEY] Error starting journey", exc_info=sys.exc_info())
    return response
