# Django
from django.utils import timezone

# Standard Library
from datetime import datetime

# Third Party
import pytest

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.statistics.kpis import monthly_activity
from squarelet.users.models import LoginLog


def login(user, client, when):
    LoginLog.objects.create(
        user=user, client=client, created_at=timezone.make_aware(when)
    )


def month(activity, name):
    return next(m for m in activity["months"] if m["month"] == name)


@pytest.mark.django_db()
@pytest.mark.freeze_time("2026-03-15 12:00:00")
class TestMonthlyActivity:
    def test_a_user_on_two_services_counts_once_toward_the_total(self, user_factory):
        user = user_factory()
        login(user, ClientFactory(name="MuckRock"), datetime(2026, 2, 3))
        login(user, ClientFactory(name="DocumentCloud"), datetime(2026, 2, 4))

        february = month(monthly_activity(), "2026-02")

        assert february["users"] == 1
        assert february["multi"] == 1

    def test_repeat_logins_to_one_service_are_not_multi_service(self, user_factory):
        user = user_factory()
        client = ClientFactory(name="MuckRock")
        login(user, client, datetime(2026, 2, 3))
        login(user, client, datetime(2026, 2, 20))

        february = month(monthly_activity(), "2026-02")

        assert february["users"] == 1
        assert february["multi"] == 0
        assert february["services"]["MuckRock"] == {"users": 1, "multi": 0}

    def test_each_service_counts_its_users_who_also_used_another(self, user_factory):
        muckrock = ClientFactory(name="MuckRock")
        documentcloud = ClientFactory(name="DocumentCloud")
        both, muckrock_only = user_factory(), user_factory()
        login(both, muckrock, datetime(2026, 2, 3))
        login(both, documentcloud, datetime(2026, 2, 3))
        login(muckrock_only, muckrock, datetime(2026, 2, 3))

        services = month(monthly_activity(), "2026-02")["services"]

        assert services["MuckRock"] == {"users": 2, "multi": 1}
        assert services["DocumentCloud"] == {"users": 1, "multi": 1}

    def test_services_in_different_months_are_not_multi_service(self, user_factory):
        user = user_factory()
        login(user, ClientFactory(name="MuckRock"), datetime(2026, 1, 30))
        login(user, ClientFactory(name="DocumentCloud"), datetime(2026, 2, 2))

        activity = monthly_activity()

        assert month(activity, "2026-01")["multi"] == 0
        assert month(activity, "2026-02")["multi"] == 0

    def test_clients_sharing_a_name_count_as_one_service(self, user_factory):
        user = user_factory()
        login(user, ClientFactory(name="MuckRock"), datetime(2026, 2, 3))
        login(user, ClientFactory(name="MuckRock"), datetime(2026, 2, 4))

        february = month(monthly_activity(), "2026-02")

        assert february["multi"] == 0
        assert february["services"] == {"MuckRock": {"users": 1, "multi": 0}}

    def test_a_late_night_login_counts_toward_the_local_month(self, user_factory):
        # 11pm in New York on January 31st is already February in UTC.
        login(user_factory(), ClientFactory(), datetime(2026, 1, 31, 23))

        activity = monthly_activity()

        assert month(activity, "2026-01")["users"] == 1
        assert month(activity, "2026-02")["users"] == 0

    def test_every_month_in_the_window_is_reported(self, user_factory):
        login(user_factory(), ClientFactory(), datetime(2025, 3, 31))
        login(user_factory(), ClientFactory(), datetime(2025, 4, 1))

        activity = monthly_activity(months=12)

        assert [m["month"] for m in activity["months"]][::11] == [
            "2025-04",
            "2026-03",
        ]
        assert len(activity["months"]) == 12
        assert month(activity, "2025-04")["users"] == 1
        assert sum(m["users"] for m in activity["months"]) == 1
        assert activity["current_month"] == "2026-03"

    def test_services_are_ordered_by_this_months_users(self, user_factory):
        quiet, busy = ClientFactory(name="A quiet service"), ClientFactory(name="Busy")
        login(user_factory(), quiet, datetime(2026, 3, 1))
        for _ in range(2):
            login(user_factory(), busy, datetime(2026, 3, 1))

        assert monthly_activity()["services"] == ["Busy", "A quiet service"]
