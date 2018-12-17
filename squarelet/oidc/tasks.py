
# Django
from celery.task import task

# Local
from .models import ClientProfile


@task(name="send_cache_invalidation")
def send_cache_invalidation(client_profile_pk, model, uuid):
    client_profile = ClientProfile.objects.get(pk=client_profile_pk)
    client_profile.send_cache_invalidation(model, uuid)
    # XXX error handling
