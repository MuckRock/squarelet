"""Utils for the OIDC app"""

# Django
from django.conf import settings

# Standard Library
import logging

# Local
from . import tasks
from .models import ClientProfile

logger = logging.getLogger(__name__)


def send_cache_invalidations(model, uuids):
    """Send a cache invalidation signal to all clients"""
    if settings.ENABLE_SEND_CACHE_INVALIDATIONS:
        logger.info("Sending cache invalidations for: %s %s", model, uuids)
        for client_profile in ClientProfile.objects.exclude(webhook_url=""):
            tasks.send_cache_invalidation.delay(client_profile.pk, model, uuids)
