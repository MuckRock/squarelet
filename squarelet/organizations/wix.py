"""Functions to interact with the Wix API"""

# Django
from django.conf import settings

# Standard Library
import logging

# Third Party
import requests

logger = logging.getLogger(__name__)


def get_contact_by_email(headers, email):
    logger.warning("[WIX-SYNC] get contact by email")
    response = requests.post(
        "https://www.wixapis.com/members/v1/members/query",
        headers=headers,
        json={
            "query": {
                "filter": {
                    "loginEmail": email,
                }
            }
        },
    )
    response.raise_for_status()
    rjson = response.json()
    logger.warning(
        "[WIX-SYNC] get contact by email response %d %s", response.status_code, rjson
    )
    if rjson["metadata"]["count"] > 0:
        return rjson["members"][0]["contactId"]
    else:
        return None


def create_member(headers, organization, user):
    logger.warning("[WIX-SYNC] create member")
    response = requests.post(
        "https://www.wixapis.com/members/v1/members",
        headers=headers,
        json={
            "member": {
                "loginEmail": user.email,
                "contact": {
                    "firstName": user.name.split(" ", 1)[0],
                    "lastName": user.name.split(" ", 1)[1],
                    "emails": [user.email],
                    "company": organization.name,
                },
            },
        },
    )
    response.raise_for_status()
    logger.warning(
        "[WIX-SYNC] create member response %d %s", response.status_code, response.json()
    )
    return response.json()["member"]["contactId"]


def add_labels(headers, contact_id, plan):
    logger.warning("[WIX-SYNC] add labels")
    plan_slug = plan.slug.split("-")[1]
    response = requests.post(
        f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
        headers=headers,
        json={"labelKeys": ["custom.paying-member", f"custom.{plan_slug}-member"]},
    )
    logger.warning(
        "[WIX-SYNC] add labels response %d %s", response.status_code, response.json()
    )
    response.raise_for_status()


def send_set_password_email(headers, email):
    logger.warning("[WIX-SYNC] send set password email")
    response = requests.post(
        "https://www.wixapis.com/wix-sm/api/v1/auth/v1/auth/members"
        "/send-set-password-email",
        headers=headers,
        json={
            "email": email,
            "hideIgnoreMessage": True,
        },
    )
    response.raise_for_status()
    logger.warning(
        "[WIX-SYNC] send set password email response %d %s",
        response.status_code,
        response.json(),
    )


def sync_wix(organization, plan, user):
    """Sync the user to Wix"""

    headers = {
        "Authorization": settings.WIX_APP_SECRET,
        "wix-site-id": settings.WIX_SITE_ID,
    }

    logger.warning(
        "[WIX-SYNC] sync wix org: %s plan: %s user: %s", organization, plan, user
    )
    contact_id = get_contact_by_email(headers, user.email)
    if contact_id is None:
        contact_id = create_member(headers, organization, user)
        # only set password for new members
        send_set_password_email(headers, user.email)
    add_labels(headers, contact_id, plan)
