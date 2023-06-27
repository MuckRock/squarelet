# Django
from django.conf import settings
from django.db.models import Q

# Standard Library
from datetime import date, timedelta

# Third Party
from dateutil.relativedelta import relativedelta

# Squarelet
from squarelet.core.mail import Email
from squarelet.organizations.models.organization import OrganizationChangeLog
from squarelet.statistics.models import Statistics


class Digest(Email):
    template = "statistics/email/digest.html"

    def __init__(self, **kwargs):
        kwargs["subject"] = "Accounts Digest"
        kwargs["to"] = settings.DIGEST_EMAILS
        current_date = kwargs.pop("date", date.today() - timedelta(1))
        kwargs["extra_context"] = self.get_context(current_date)
        super().__init__(**kwargs)

    def get_context(self, current_date):
        return {
            "date": current_date,
            "stats": self.get_stats(current_date),
            "pro_users": self.get_pro_users(current_date),
            "org_changes": self.get_org_changes(current_date),
        }

    def get_stats(self, current_date):
        stats = []

        def format_stat(name):
            return " ".join(s.capitalize() for s in name.split("_"))

        try:
            current = Statistics.objects.get(date=current_date)
        except Statistics.DoesNotExist:
            return stats
        day = Statistics.objects.filter(
            date=current_date - relativedelta(days=1)
        ).first()
        week = Statistics.objects.filter(
            date=current_date - relativedelta(weeks=1)
        ).first()
        month = Statistics.objects.filter(
            date=current_date - relativedelta(months=1)
        ).first()

        numeric_stats = [
            "total_users",
            "total_users_excluding_agencies",
            "total_users_pro",
            "total_users_org",
            "total_orgs",
            "verified_orgs",
        ]
        previous = [day, week, month]
        for stat in numeric_stats:
            value = getattr(current, stat)
            stats.append(
                (
                    format_stat(stat),
                    value,
                    [value - getattr(p, stat) if p else None for p in previous],
                )
            )

        return stats

    def get_pro_users(self, current_date):
        pro_users = {}
        try:
            current = Statistics.objects.get(date=current_date)
            yesterday = Statistics.objects.get(
                date=current_date - relativedelta(days=1)
            )
        except Statistics.DoesNotExist:
            return pro_users

        current_pro_users = set(u.username for u in current.pro_users.all())
        yesterday_pro_users = set(u.username for u in yesterday.pro_users.all())
        pro_users["gained"] = current_pro_users - yesterday_pro_users
        pro_users["lost"] = yesterday_pro_users - current_pro_users

        return pro_users

    def get_org_changes(self, current_date):
        return OrganizationChangeLog.objects.filter(
            ~Q(from_plan=None) | ~Q(to_plan=None),
            created_at__gte=current_date,
            created_at__lt=current_date + timedelta(1),
            organization__individual=False,
        ).select_related("organization")
