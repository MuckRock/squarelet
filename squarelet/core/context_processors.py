# Django
from django.conf import settings as django_settings
from django.utils.functional import SimpleLazyObject


def settings(request):
    return {"settings": django_settings}


def payment_failed(request):
    if request.user.is_authenticated:
        payment_failed_organizations = request.user.organizations.filter(
            memberships__admin=True, payment_failed=True
        )
    else:
        payment_failed_organizations = None
    return {"payment_failed_organizations": payment_failed_organizations}


def mixpanel(request):
    """
    Retrieve and delete any mixpanel analytics session data and send it to the template
    """
    return {
        "mp_events": SimpleLazyObject(lambda _: request.session.pop("mp_events", [])),
        "mp_alias": SimpleLazyObject(lambda _: request.session.pop("mp_alias", False)),
        "mp_charge": SimpleLazyObject(lambda _: request.session.pop("mp_charge", 0)),
        "mp_token": django_settings.MIXPANEL_TOKEN,
    }
