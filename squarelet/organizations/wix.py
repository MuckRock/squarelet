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
        timeout=(5, 15),
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
        timeout=(5, 15),
    )
    response.raise_for_status()
    logger.warning(
        "[WIX-SYNC] create member response %d %s", response.status_code, response.json()
    )
    return response.json()["member"]["contactId"]


def get_tier_from_plan(plan):
    """Extract the tier name (essential, enhanced, enterprise) from a plan slug.

    Handles all variants: sunlight-essential, sunlight-enterprise-custom,
    sunlight-nonprofit-enhanced-annual, etc. Also maps legacy tier names
    (basic→essential, premium→enhanced) to their current equivalents.
    """
    tier_aliases = {
        "enterprise": "enterprise",
        "enhanced": "enhanced",
        "essential": "essential",
        "basic": "essential",
        "premium": "enhanced",
    }
    return next(
        (label for alias, label in tier_aliases.items() if alias in plan.slug),
        plan.slug,
    )


def add_labels(headers, contact_id, plan):
    logger.warning("[WIX-SYNC] add labels")
    tier = get_tier_from_plan(plan)
    response = requests.post(
        f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
        headers=headers,
        json={"labelKeys": ["custom.paying-member", f"custom.{tier}-member"]},
        timeout=(5, 15),
    )
    logger.warning(
        "[WIX-SYNC] add labels response %d %s", response.status_code, response.json()
    )
    response.raise_for_status()


def remove_labels(headers, contact_id, plan, label_keys=None):
    """Remove Wix labels from a contact.

    If label_keys is provided, remove exactly those labels.
    Otherwise, remove the default labels for the given plan.
    """
    logger.warning("[WIX-SYNC] remove labels")
    if label_keys is None:
        tier = get_tier_from_plan(plan)
        label_keys = ["custom.paying-member", f"custom.{tier}-member"]
    response = requests.delete(
        f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
        headers=headers,
        json={"labelKeys": label_keys},
        timeout=(5, 15),
    )
    logger.warning(
        "[WIX-SYNC] remove labels response %d %s",
        response.status_code,
        response.json(),
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
        timeout=(5, 15),
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


def unsync_wix(organization, plan, user):
    """Remove Wix labels for a user when they leave an organization or plan changes.

    The user's still-qualified labels are computed from their current memberships.
    Callers must ensure any relevant membership/plan changes are persisted before
    invoking this function (e.g. by dispatching the task via transaction.on_commit).
    """
    remaining_labels = get_wix_labels_for_user(user)

    headers = {
        "Authorization": settings.WIX_APP_SECRET,
        "wix-site-id": settings.WIX_SITE_ID,
    }

    logger.warning(
        "[WIX-SYNC] unsync wix org: %s plan: %s user: %s", organization, plan, user
    )
    contact_id = get_contact_by_email(headers, user.email)
    if contact_id is None:
        logger.warning(
            "[WIX-SYNC] contact not found for %s, skipping label removal", user.email
        )
        return

    # Compute which labels to actually remove
    tier = get_tier_from_plan(plan)
    plan_labels = {"custom.paying-member", f"custom.{tier}-member"}
    labels_to_remove = sorted(plan_labels - remaining_labels)

    if not labels_to_remove:
        logger.warning(
            "[WIX-SYNC] all labels for %s still needed, skipping removal", user.email
        )
        return

    remove_labels(headers, contact_id, plan, label_keys=labels_to_remove)


def get_wix_labels_for_user(user):
    """Get all Wix labels a user qualifies for across all their memberships."""
    labels = set()
    for membership in user.memberships.select_related("organization___plan").all():
        org = membership.organization
        plan = org.plan
        if plan and plan.wix:
            tier = get_tier_from_plan(plan)
            labels.add(f"custom.{tier}-member")
            labels.add("custom.paying-member")
        for _group, group_plan in org.get_wix_plans_from_groups():
            tier = get_tier_from_plan(group_plan)
            labels.add(f"custom.{tier}-member")
            labels.add("custom.paying-member")
    return labels


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
        timeout=(5, 15),
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
        timeout=(5, 15),
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
            timeout=(5, 15),
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
