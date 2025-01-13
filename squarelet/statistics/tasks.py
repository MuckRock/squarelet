# Django
from celery import shared_task
from django.utils import timezone

# Standard Library
from datetime import date, datetime, time, timedelta

# Squarelet
from squarelet.organizations.models import Organization
from squarelet.statistics.mail import Digest
from squarelet.statistics.models import Statistics
from squarelet.users.models import User


@shared_task
def store_statistics():
    """Store the daily statistics"""
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
        organizations__plans__slug="professional"
    ).count()
    kwargs["total_users_org"] = User.objects.filter(
        organizations__plans__slug="organization"
    ).count()
    kwargs["total_orgs"] = Organization.objects.exclude(
        individual=True, plans=None
    ).count()
    kwargs["verified_orgs"] = Organization.objects.filter(
        verified_journalist=True
    ).count()
    stats = Statistics.objects.create(**kwargs)

    # stats needs to be saved before many to many relationships can be set
    stats.users_today.set(
        User.objects.filter(last_login__range=(yesterday_midnight, today_midnight))
    )
    stats.pro_users.set(User.objects.filter(organizations__plans__slug="professional"))
    stats.save()


@shared_task
def send_digest():
    Digest().send()
