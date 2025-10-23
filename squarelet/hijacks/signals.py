# Django
from django.dispatch import receiver

# Third Party
from hijack.signals import hijack_ended, hijack_started

# Local
from .models import HijackLog


@receiver(hijack_started)
def log_hijack_start(sender, hijacker_id, hijacked_id, **kwargs):
    HijackLog.objects.create(
        hijacker_id=hijacker_id,
        hijacked_id=hijacked_id,
        action="start",
    )


@receiver(hijack_ended)
def log_hijack_end(sender, hijacker_id, hijacked_id, **kwargs):
    HijackLog.objects.create(
        hijacker_id=hijacker_id,
        hijacked_id=hijacked_id,
        action="end",
    )
