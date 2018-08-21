"""Functions to update information on other sites when someone updates their
information on squarelet"""

# Django
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist

# Third Party
import requests


def muckrock(user):
    url = f"{settings.MUCKROCK_URL}/api_v1/user/{user.pk}/"
    print(url)
    headers = {
        "Authorization": f"Token {settings.MUCKROCK_TOKEN}",
        "content-type": "application/json",
    }
    data = {
        "profile": {"full_name": user.name, "avatar_url": user.avatar_url},
        "username": user.username,
    }
    try:
        email = user.emailaddress_set.get(primary=True)
        data["email"] = email.email
        data["profile"]["email_confirmed"] = email.verified
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        pass
    return requests.patch(url, json=data, headers=headers)


def doccloud(_user):
    pass
