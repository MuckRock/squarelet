# Django
from celery.schedules import crontab
from celery.task import periodic_task
from django.db.models import F

# Standard Library
from datetime import date

# Local
from .models import Organization


@periodic_task(run_every=crontab(hour=0, minute=5), name="restore_organizations")
def restore_organization():
    Organization.objects.filter(date_update__lte=date.today()).update(
        date_update=date.today(),  # XXX fix this
        plan=F("next_plan"),
        monthly_requests=F("requests_per_month"),
        monthly_pages=F("pages_per_month"),
    )
