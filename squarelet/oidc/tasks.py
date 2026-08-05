# Django
from celery import shared_task
from django.utils import timezone

# Standard Library
import logging

# Local
from .models import ClientProfile

logger = logging.getLogger(__name__)


@shared_task(name="squarelet.oidc.tasks.send_cache_invalidation")
def send_cache_invalidation(client_profile_pk, model, uuids, invalidation_id=None):
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
        client_profile.send_cache_invalidation(model, uuids)
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
