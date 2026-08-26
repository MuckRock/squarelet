"""Utils for the OIDC app"""

# Django
from django.conf import settings
from django.db.models.expressions import F

# Standard Library
import logging
import uuid as uuid_lib

# Local
from . import tasks
from .models import ClientProfile, format_uuids

logger = logging.getLogger(__name__)


def send_cache_invalidations(model, uuids):
    """Send a cache invalidation signal to all clients"""
    uuids = list(uuids)
    formatted_uuids = format_uuids(uuids)

    if not settings.ENABLE_SEND_CACHE_INVALIDATIONS:
        # the standing alarm for this being off in production is a single
        # warning at startup, in OidcConfig.ready
        logger.info(
            "[CACHE-INVALIDATION] Disabled by ENABLE_SEND_CACHE_INVALIDATIONS - "
            "dropping model=%s count=%d uuids=%s",
            model,
            len(uuids),
            formatted_uuids,
        )
        return

    client_profiles = list(
        ClientProfile.objects.exclude(webhook_url="").select_related("client")
    )
    if not client_profiles:
        logger.info(
            "[CACHE-INVALIDATION] No client has a webhook_url configured - "
            "dropping model=%s count=%d",
            model,
            len(uuids),
        )
        return

    # short correlation id so one logical broadcast is greppable across the fan-out
    invalidation_id = uuid_lib.uuid4().hex[:8]
    logger.info(
        "[CACHE-INVALIDATION] Dispatching id=%s model=%s count=%d clients=%s "
        "uuids=%s",
        invalidation_id,
        model,
        len(uuids),
        [cp.client.name for cp in client_profiles],
        formatted_uuids,
    )
    for client_profile in client_profiles:
        # keyword argument with a default so messages already queued in Redis at
        # deploy time still deserialize
        tasks.send_cache_invalidation.delay(
            client_profile.pk, model, uuids, invalidation_id=invalidation_id
        )


def oidc_login_hook(request, user, client):
    """Log which client users login to"""
    # take an arbitrary non-individual organization, since most users will have one org
    organizations = list(
        user.organizations.values("id", "name", plan=F("subscriptions__plans__name"))
    )
    user.logins.create(
        client=client,
        metadata={
            "organizations": organizations,
        },
    )
