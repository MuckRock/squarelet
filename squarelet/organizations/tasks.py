# Django
from celery.schedules import crontab
from celery.task import periodic_task
from django.db.models import F

# Standard Library
from datetime import date

# Squarelet
from squarelet.core.models import Interval
from squarelet.oidc.middleware import send_cache_invalidations

# Local
from .models import Organization


@periodic_task(run_every=crontab(hour=0, minute=5), name="restore_organizations")
def restore_organization():
    organizations = Organization.objects.filter(date_update__lte=date.today())
    uuids = organizations.values_list("pk", flat=True)
    organizations.update(
        date_update=date.today() + Interval("1 month"), plan=F("next_plan")
    )
    # XXX send single cache invalidation for all uuids
    for uuid in uuids:
        send_cache_invalidations("organization", uuid)
