
# Django
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist


def userinfo(claims, user):
    claims['name'] = user.name
    claims['preferred_username'] = user.username
    claims['updated_at'] = user.updated_at

    try:
        email = user.emailaddress_set.get(primary=True)
        claims['email'] = email.email
        claims['email_verified'] = email.verified
    except (ObjectDoesNotExist, MultipleObjectsReturned):
        pass

    return claims
