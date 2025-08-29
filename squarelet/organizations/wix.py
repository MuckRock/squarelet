"""Functions to interact with the Wix API"""

# Django
from django.conf import settings

# Third Party
import requests


def get_contact_by_email(headers, email):
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
    if rjson["metadata"]["count"] > 0:
        return rjson["members"][0]["contactId"]
    else:
        return None


def create_member(headers, organization, user):
    response = requests.post(
        "https://www.wixapis.com/members/v1/members",
        headers=headers,
        json={
            "member": {
                "loginEmail": user.email,
                "contact": {
                    "firstName": user.name.split(" ", 1)[0],
                    "lastName": user.name.split(" ", 1)[0],
                    "emails": [user.email],
                    "company": organization.name,
                },
            },
        },
    )
    response.raise_for_status()
    return response.json()["member"]["contactId"]


def add_labels(headers, contact_id, plan):
    plan_slug = plan.slug.split("-")[1]
    response = requests.post(
        f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
        headers=headers,
        json={"labelKeys": ["custom.paying-member", f"custom.{plan_slug}-member"]},
    )
    response.raise_for_status()


def send_set_password_email(headers, email):
    requests.post(
        "https://www.wixapis.com/wix-sm/api/v1/auth/v1/auth/members"
        "/send-set-password-email",
        headers=headers,
        json={
            "email": email,
            "hideIgnoreMessage": True,
        },
    )


def sync_wix(organization, plan, user):
    """Sync the user to Wix"""

    headers = {
        "Authorization": settings.WIX_APP_SECRET,
        "wix-site-id": settings.WIX_SITE_ID,
    }

    contact_id = get_contact_by_email(headers, user.email)
    if contact_id is None:
        contact_id = create_member(headers, organization, user)
    add_labels(headers, contact_id, plan)
    send_set_password_email(headers, user.email)
