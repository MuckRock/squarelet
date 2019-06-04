# Django
from celery.schedules import crontab
from celery.task import periodic_task
from django.utils import timezone

# Standard Library
from datetime import date, datetime, time, timedelta

# Squarelet
from squarelet.organizations.models import Organization
from squarelet.users.models import User

# Local
from .models import Statistics


# This is using UTC time instead of the local timezone
@periodic_task(
    run_every=crontab(hour=5, minute=30),
    name="squarelet.statistics.tasks.store_statistics",
)
def store_statistics():
    """Store the daily statistics"""
    # pylint: disable=too-many-statements

    midnight = time(tzinfo=timezone.get_current_timezone())
    today_midnight = datetime.combine(date.today(), midnight)
    yesterday = date.today() - timedelta(1)
    yesterday_midnight = today_midnight - timedelta(1)

    kwargs = {}
    kwargs["date"] = yesterday
    kwargs["total_users"] = User.objects.count()
    kwargs["total_users_excluding_agencies"] = User.objects.exclude(
        is_agency=True
    ).count()
    kwargs["total_users_pro"] = User.objects.filter(
        organizations__plan__slug="professional"
    ).count()
    kwargs["total_users_org"] = User.objects.filter(
        organizations__plan__slug="organization"
    ).count()
    kwargs["total_orgs"] = Organization.objects.exclude(
        individual=True, plan__slug="free"
    ).count()
    stats = Statistics.objects.create(**kwargs)

    # stats needs to be saved before many to many relationships can be set
    stats.users_today.set(
        User.objects.filter(last_login__range=(yesterday_midnight, today_midnight))
    )
    stats.pro_users.set(User.objects.filter(organizations__plan__slug="professional"))
    stats.save()
