# Django
from django.conf import settings as django_settings

# Squarelet
from squarelet.organizations.models import Role


def settings(request):
    return {"settings": django_settings}


def payment_failed(request):
    if request.user.is_authenticated:
        payment_failed_organizations = request.user.organizations.filter(
            memberships__role=Role.administrator, payment_failed=True
        )
    else:
        payment_failed_organizations = None
    return {"payment_failed_organizations": payment_failed_organizations}
