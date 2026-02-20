# Django
from celery import shared_task
from django.utils import timezone

# Local
from .models import ClientProfile


@shared_task(name="squarelet.oidc.tasks.send_cache_invalidation")
def send_cache_invalidation(client_profile_pk, model, uuids):
    # pylint: disable=import-outside-toplevel
    from squarelet.organizations.models import Organization
    from squarelet.users.models import User

    client_profile = ClientProfile.objects.get(pk=client_profile_pk)
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
