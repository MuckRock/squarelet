<<<<<<< HEAD
# Third Party
from allauth.account import signals


def email_confirmed(request, email_address, **kwargs):
    if email_address.primary:
        pass
        # XXX send cache invalidation for user
        # sync.delay("User", "update", email_address.user.pk)


def email_changed(request, user, from_email_address, to_email_address, **kwargs):
    pass
    # XXX send cache invalidation for user
    # sync.delay("User", "update", user.pk)
=======
# Django
from django.db import transaction
from django.utils.translation import ugettext_lazy as _

# Third Party
from allauth.account import signals

# Squarelet
from squarelet.core.mail import send_mail
from squarelet.oidc.middleware import send_cache_invalidations


def email_confirmed(request, email_address, **kwargs):
    if email_address.primary:
        send_cache_invalidations("user", email_address.user.pk)


def email_changed(request, user, from_email_address, to_email_address, **kwargs):
    """The user has changed their primary email"""
    # update their stripe customer
    customer = user.individual_organization.customer
    customer.email = to_email_address.email
    customer.save()
    # clear the email failed flag
    with transaction.atomic():
        user.email_failed = False
        user.save()
        # send client sites a cache invalidation to update this user's info
        transaction.on_commit(lambda: send_cache_invalidations("user", user.pk))
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
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c


signals.email_confirmed.connect(
    email_confirmed, dispatch_uid="squarelet.users.signals.email_confirmed"
)
signals.email_changed.connect(
    email_changed, dispatch_uid="squarelet.users.signals.email_changed"
)
