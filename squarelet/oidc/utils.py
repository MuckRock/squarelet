"""Utils for the OIDC app"""

# Standard Library
import logging

# Local
from . import tasks
from .models import ClientProfile

logger = logging.getLogger(__name__)


def send_cache_invalidations(model, uuid):
    """Send a cache invalidation signal to all clients"""
    logger.info("Sending cache invalidations for: %s %s", model, uuid)
    for client_profile in ClientProfile.objects.exclude(webhook_url=""):
        tasks.send_cache_invalidation.delay(client_profile.pk, model, uuid)
