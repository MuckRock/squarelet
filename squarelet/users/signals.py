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


signals.email_confirmed.connect(
    email_confirmed, dispatch_uid="squarelet.users.signals.email_confirmed"
)
signals.email_changed.connect(
    email_changed, dispatch_uid="squarelet.users.signals.email_changed"
)
