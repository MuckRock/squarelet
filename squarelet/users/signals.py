
# Third Party
from allauth.account import signals

# Squarelet
from squarelet.users.tasks import push_update_user


def email_confirmed(request, email_address, **kwargs):
    if email_address.primary:
        push_update_user.delay(email_address.user.pk)


def email_changed(request, user, from_email_address, to_email_address, **kwargs):
    push_update_user.delay(user.pk)


signals.email_confirmed.connect(
    email_confirmed, dispatch_uid="squarelet.users.signals.email_confirmed"
)
signals.email_changed.connect(
    email_changed, dispatch_uid="squarelet.users.signals.email_changed"
)
