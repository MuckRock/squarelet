"""Functions to update information on other sites when someone updates their
information on squarelet"""

# Django
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist

# Local
from ..core.update import muckrock_api


def muckrock(user):
    data = {
        "profile": {"full_name": user.name, "avatar_url": user.avatar_url},
        "username": user.username,
    }
    try:
        email = user.emailaddress_set.get(primary=True)
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        pass
    else:
        data["email"] = email.email
        data["profile"]["email_confirmed"] = email.verified

    return muckrock_api(f"/user/{user.pk}", data)


def doccloud(_user):
    pass
