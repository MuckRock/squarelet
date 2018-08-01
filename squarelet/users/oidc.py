
# Django
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist


def userinfo(claims, user):
    claims["name"] = user.name
    claims["preferred_username"] = user.username
    claims["updated_at"] = user.updated_at
    if user.avatar.url.startswith("http"):
        claims["picture"] = user.avatar.url
    else:
        claims["picture"] = f"{settings.SQUARELET_URL}{user.avatar.url}"

    try:
        email = user.emailaddress_set.get(primary=True)
        claims["email"] = email.email
        claims["email_verified"] = email.verified
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        pass

    return claims
