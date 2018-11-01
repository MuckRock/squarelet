# Django
from celery.schedules import crontab
from celery.task import periodic_task, task
from django.db.models import F

# Standard Library
from datetime import date

# Local
from . import update
from .models import Organization


@periodic_task(run_every=crontab(hour=0, minute=5), name="restore_organizations")
def restore_organization():
    Organization.objects.filter(date_update__lte=date.today()).update(
        date_update=date.today(),  # XXX fix this
        plan=F("next_plan"),
        monthly_requests=F("requests_per_month"),
        monthly_pages=F("pages_per_month"),
    )


# XXX check http responses and retry on error's if appropriate
# make this code DRYer


@task(name="update_muckrock_organization")
def update_muckrock_organization(organization_pk):
    organization = Organization.objects.get(pk=organization_pk)
    update.muckrock(organization)


@task(name="update_doccloud_organization")
def update_doccloud_organization(organization_pk):
    organization = Organization.objects.get(pk=organization_pk)
    update.doccloud(organization)


@task(name="update_all_organization")
def push_update_organization(organization_pk):
    updaters = [update_muckrock_organization]
    for updater in updaters:
        updater.delay(organization_pk)


@task(name="update_muckrock_add_member")
def update_muckrock_add_member(organization_pk, user_pk):
    update.muckrock_add_member(organization_pk, user_pk)


@task(name="update_doccloud_add_member")
def update_doccloud_add_member(organization_pk, user_pk):
    update.doccloud_add_member(organization_pk, user_pk)


@task(name="update_all_add_member")
def push_update_add_member(organization_pk, user_pk):
    updaters = [update_muckrock_add_member]
    for updater in updaters:
        updater.delay(organization_pk, user_pk)


@task(name="update_muckrock_remove_member")
def update_muckrock_remove_member(organization_pk, user_pk):
    update.muckrock_remove_member(organization_pk, user_pk)


@task(name="update_doccloud_remove_member")
def update_doccloud_remove_member(organization_pk, user_pk):
    update.doccloud_remove_member(organization_pk, user_pk)


@task(name="update_all_remove_member")
def push_update_remove_member(organization_pk, user_pk):
    updaters = [update_muckrock_remove_member]
    for updater in updaters:
        updater.delay(organization_pk, user_pk)
