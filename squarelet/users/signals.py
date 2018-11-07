# Third Party
from allauth.account import signals

# Squarelet
from squarelet.syncers.tasks import sync


def email_confirmed(request, email_address, **kwargs):
    if email_address.primary:
        sync.delay("User", "update", email_address.user.pk)


def email_changed(request, user, from_email_address, to_email_address, **kwargs):
    sync.delay("User", "update", user.pk)


signals.email_confirmed.connect(
    email_confirmed, dispatch_uid="squarelet.users.signals.email_confirmed"
)
signals.email_changed.connect(
    email_changed, dispatch_uid="squarelet.users.signals.email_changed"
)
signals.user_signed_up.connect(
    user_signed_up, dispatch_uid="squarelet.users.signals.user_signed_up"
)
