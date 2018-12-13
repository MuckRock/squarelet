"""Utils for the OIDC app"""

# Local
from . import tasks
from .models import ClientProfile


def send_cache_invalidations(model, uuid):
    """Send a cache invalidation signal to all clients"""
    # XXX error handling
    for client_profile in ClientProfile.objects.exclude(webhook_url=""):
        tasks.send_cache_invalidation.delay(client_profile.pk, model, uuid)
