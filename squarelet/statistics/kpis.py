# Django
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

# Standard Library
from datetime import date, datetime

# Third Party
from oidc_provider.models import Client

# Squarelet
from squarelet.users.models import LoginLog

MONTHS = 24
CACHE_SECONDS = 60 * 60

# Services are grouped by client name, so a user on two clients sharing a name
# is not counted as multi-service.
ACTIVITY_SQL = f"""
WITH user_months AS (
    SELECT
        date_trunc('month', log.created_at AT TIME ZONE %(tz)s)::date AS month,
        log.user_id,
        array_agg(DISTINCT client.name) AS services
    FROM {LoginLog._meta.db_table} log
    JOIN {Client._meta.db_table} client ON client.id = log.client_id
    WHERE log.created_at >= %(start)s
    GROUP BY 1, 2
)
SELECT
    month,
    NULL AS service,
    count(*),
    count(*) FILTER (WHERE cardinality(services) > 1)
FROM user_months
GROUP BY month
UNION ALL
SELECT
    month,
    service,
    count(*),
    count(*) FILTER (WHERE cardinality(services) > 1)
FROM user_months CROSS JOIN LATERAL unnest(services) AS service
GROUP BY month, service
"""


def _add_months(month, count):
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def monthly_activity(months=MONTHS):
    """Active and multi-service users per month, overall and per service.

    Months run oldest first and end with the current, partial month; a month
    with no logins is present with zero users.
    """
    today = timezone.localdate()
    current = today.replace(day=1)
    first = _add_months(current, 1 - months)
    start = timezone.make_aware(datetime(first.year, first.month, 1))

    rows = {
        _add_months(first, i): {"users": 0, "multi": 0, "services": {}}
        for i in range(months)
    }
    with connection.cursor() as cursor:
        cursor.execute(
            ACTIVITY_SQL,
            {"tz": timezone.get_current_timezone_name(), "start": start},
        )
        for month, service, users, multi in cursor.fetchall():
            row = rows[month]
            if service is None:
                row["users"], row["multi"] = users, multi
            else:
                row["services"][service] = {"users": users, "multi": multi}

    latest = rows[current]["services"]
    services = sorted(
        {name for row in rows.values() for name in row["services"]},
        key=lambda name: (-latest.get(name, {}).get("users", 0), name),
    )
    return {
        "current_month": current.strftime("%Y-%m"),
        "services": services,
        "months": [
            {"month": month.strftime("%Y-%m"), **row} for month, row in rows.items()
        ],
    }


def cached_monthly_activity(months=MONTHS):
    """`monthly_activity`, cached for an hour; the query scans every login in range."""
    key = f"statistics:kpis:{timezone.localdate():%Y-%m}:{months}"
    return cache.get_or_set(key, lambda: monthly_activity(months), CACHE_SECONDS)
