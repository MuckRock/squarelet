from django.dispatch import receiver
from hijack.signals import hijack_started, hijack_ended
from squarelet.users.models import User
from actstream import registry
from squarelet.core.utils import new_action

registry.register(User)

@receiver(hijack_started)
def on_hijack_started(sender, hijacker, hijacked, request, **kwargs):
    new_action(
        actor=hijacker,
        verb="hijacked",
        target=hijacked,
    )


@receiver(hijack_ended)
def on_hijack_ended(sender, hijacker, hijacked, request, **kwargs):
    new_action(
        actor=hijacker,
        verb="ended hijack",
        target=hijacked,
    )
