"""Functions to interact with the Wix API"""

# Django
from django.conf import settings

# Standard Library
import logging
import sys

# Third Party
import requests

logger = logging.getLogger(__name__)


def get_contact_names(user):
    """Get first and last name from user.name"""
    name_parts = user.name.split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    return first_name, last_name


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
    first_name, last_name = get_contact_names(user)

    response = requests.post(
        "https://www.wixapis.com/members/v1/members",
        headers=headers,
        json={
            "member": {
                "loginEmail": user.email,
                "contact": {
                    "firstName": first_name,
                    "lastName": last_name,
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
    # Extract the tier name (essential, enhanced, enterprise) from the slug
    # Handles: sunlight-essential, sunlight-essential-annual,
    #          sunlight-nonprofit-essential, sunlight-nonprofit-essential-annual, etc.
    plan_slug = (
        plan.slug.replace("sunlight-", "")
        .replace("nonprofit-", "")
        .replace("-annual", "")
    )
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


def create_contact(headers, organization, user):
    """Create a contact in Wix using the Contacts API"""
    logger.warning("[WIX-CONTACT] create contact")
    first_name, last_name = get_contact_names(user)

    response = requests.post(
        "https://www.wixapis.com/contacts/v4/contacts",
        headers=headers,
        json={
            "info": {
                "name": {
                    "first": first_name,
                    "last": last_name,
                },
                "emails": {
                    "items": [
                        {
                            "email": user.email,
                            "tag": "MAIN",
                        }
                    ]
                },
                "company": organization.name,
            }
        },
    )
    response.raise_for_status()
    logger.warning(
        "[WIX-CONTACT] create contact response %d %s",
        response.status_code,
        response.json(),
    )
    return response.json()["contact"]["id"]


def get_contact_by_email_v4(headers, email):
    """Query for a contact by email using Contacts API v4"""
    logger.warning("[WIX-CONTACT] get contact by email")
    response = requests.post(
        "https://www.wixapis.com/contacts/v4/contacts/query",
        headers=headers,
        json={
            "query": {
                "filter": {
                    "info.emails.email": email,
                }
            }
        },
    )
    response.raise_for_status()
    rjson = response.json()
    logger.warning(
        "[WIX-CONTACT] get contact by email response %d %s",
        response.status_code,
        rjson,
    )
    if rjson.get("contacts") and len(rjson["contacts"]) > 0:
        return rjson["contacts"][0]["id"]
    else:
        return None


def add_to_waitlist(organization, plan, user):
    """Add user to waitlist in Wix

    Get or create a contact and apply two labels:
    - "custom.waitlist" (generic waitlist label)
    - "custom.waitlist-{plan-slug}" (plan-specific waitlist label)
    """
    headers = {
        "Authorization": settings.WIX_APP_SECRET,
        "wix-site-id": settings.WIX_SITE_ID,
    }

    logger.warning(
        "[WIX-WAITLIST] Adding to waitlist: %s for plan %s", user.email, plan.name
    )

    try:
        # Get or create contact using Contacts API
        contact_id = get_contact_by_email_v4(headers, user.email)
        if contact_id is None:
            contact_id = create_contact(headers, organization, user)

        # Add waitlist labels: generic + plan-specific
        plan_label = f"custom.waitlist-{plan.slug}"
        response = requests.post(
            f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
            headers=headers,
            json={"labelKeys": ["custom.waitlist", plan_label]},
        )
        response.raise_for_status()
        logger.warning("[WIX-WAITLIST] Successfully added to waitlist: %s", user.email)
    except requests.exceptions.RequestException as exc:
        logger.error(
            "[WIX-WAITLIST] Failed to add %s to waitlist: %s",
            user.email,
            exc,
            exc_info=sys.exc_info(),
        )
