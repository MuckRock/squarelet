# Django
from celery import shared_task
from django.utils import timezone

# Standard Library
import logging
import sys
from random import randint

# Third Party
import requests

# Local
from .models import ClientProfile, format_uuids

logger = logging.getLogger(__name__)

# A client outage is measured in minutes, not seconds: 1, 2 and 4 minutes plus
# jitter, so a client coming back up is not hit by every retry at once
MAX_RETRIES = 3
RETRY_BACKOFF = 60
RETRY_JITTER = 30


def retry_countdown(retries):
    """Seconds to wait before the next delivery attempt"""
    return 2**retries * RETRY_BACKOFF + randint(0, RETRY_JITTER)


@shared_task(
    bind=True,
    max_retries=MAX_RETRIES,
    name="squarelet.oidc.tasks.send_cache_invalidation",
)
def send_cache_invalidation(
    self, client_profile_pk, model, uuids, invalidation_id=None
):
    # pylint: disable=import-outside-toplevel
    # Squarelet
    from squarelet.organizations.models import Organization
    from squarelet.users.models import User

    client_profile = ClientProfile.objects.select_related("client").get(
        pk=client_profile_pk
    )
    original_count = len(uuids)
    if client_profile.client.require_consent:
        # If this client requires consent, we must filter out the users or orgs
        # to just the ones that they have permissions to view
        if model == "user":
            # The user model's UUID field is named `individual_organization_id`
            # because it is a ForeignKey to the individual organization, so that
            # a user and their individual organization always share a UUID
            users = User.objects.filter(
                individual_organization_id__in=uuids,
                userconsent__client=client_profile.client,
                userconsent__expires_at__gt=timezone.now(),
            )
            uuids = [
                str(i)
                for i in users.values_list("individual_organization_id", flat=True)
            ]
        elif model == "organization":
            organizations = Organization.objects.filter(
                uuid__in=uuids,
                users__userconsent__client=client_profile.client,
                users__userconsent__expires_at__gt=timezone.now(),
            ).distinct()
            uuids = [str(i) for i in organizations.values_list("uuid", flat=True)]

    if uuids:
        try:
            client_profile.send_cache_invalidation(model, uuids, invalidation_id)
        except requests.RequestException as exc:
            # the model logs each rejected or failed attempt at warning level
            if self.request.retries >= self.max_retries:
                # the one error per lost delivery, so one Sentry event - the task
                # itself succeeds, as a dropped invalidation only leaves the
                # client's cache stale until its next write
                logger.error(
                    "[CACHE-INVALIDATION] Retries exceeded, giving up! id=%s "
                    "client=%s url=%s model=%s count=%d attempts=%d uuids=%s: %s",
                    invalidation_id,
                    client_profile.client.name,
                    client_profile.webhook_url,
                    model,
                    len(uuids),
                    self.request.retries + 1,
                    format_uuids(uuids),
                    exc,
                    exc_info=sys.exc_info(),
                )
                return
            countdown = retry_countdown(self.request.retries)
            logger.info(
                "[CACHE-INVALIDATION] Retrying id=%s client=%s url=%s model=%s "
                "count=%d attempt=%d/%d countdown=%d",
                invalidation_id,
                client_profile.client.name,
                client_profile.webhook_url,
                model,
                len(uuids),
                self.request.retries + 1,
                self.max_retries + 1,
                countdown,
            )
            raise self.retry(countdown=countdown, exc=exc)
    else:
        # this drop was previously indistinguishable from a successful send
        logger.info(
            "[CACHE-INVALIDATION] Nothing to send id=%s client=%s model=%s "
            "reason=%s original_count=%d",
            invalidation_id,
            client_profile.client.name,
            model,
            "consent-filtered" if original_count else "empty-input",
            original_count,
        )
