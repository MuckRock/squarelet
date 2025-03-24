# Django
from django.db import transaction
from django.utils.translation import gettext_lazy as _

# Third Party
from allauth.account import signals

# Squarelet
from squarelet.core.mail import send_mail
from squarelet.oidc.middleware import send_cache_invalidations


def user_logged_in(request, user, **kwargs):
    """The user has logged in"""
    # perform onboarding checks
    print("User logged in:", user)
    print("Login request:", request)


def email_confirmed(request, email_address, **kwargs):
    if email_address.primary:
        send_cache_invalidations("user", email_address.user.uuid)


def email_changed(request, user, from_email_address, to_email_address, **kwargs):
    """The user has changed their primary email"""
    # update the stripe customer for all accounts
    # Leave out presspass for now, as they do not have a stripe account yet
    customer = user.individual_organization.customer().stripe_customer
    customer.email = to_email_address.email
    customer.save()

    # clear the email failed flag
    with transaction.atomic():
        user.email_failed = False
        user.save()
        # send client sites a cache invalidation to update this user's info
        transaction.on_commit(lambda: send_cache_invalidations("user", user.uuid))

    # send the user a notification
    send_mail(
        subject=_("Changed email address"),
        template="users/email/email_change.html",
        to=[from_email_address.email],
        extra_context={
            "from_email_address": from_email_address.email,
            "to_email_address": to_email_address.email,
        },
    )


signals.email_confirmed.connect(
    email_confirmed, dispatch_uid="squarelet.users.signals.email_confirmed"
)
signals.email_changed.connect(
    email_changed, dispatch_uid="squarelet.users.signals.email_changed"
)
signals.user_logged_in.connect(
    user_logged_in, dispatch_uid="squarelet.users.signals.user_logged_in"
)
