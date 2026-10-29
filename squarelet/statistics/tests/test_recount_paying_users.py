# Django
from django.core.management import call_command

# Standard Library
from datetime import date

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    PlanPriceFactory,
    ProfessionalPlanFactory,
    SubscriptionItemFactory,
)
from squarelet.users.tests.factories import UserFactory

# Local
from ..models import Statistics


def _stats(day, comped):
    stats = Statistics.objects.create(
        date=day,
        total_users=0,
        total_users_excluding_agencies=0,
        total_users_pro=2,
        total_users_org=5,
        total_users_mfa=0,
        total_orgs=0,
        verified_orgs=0,
    )
    stats.pro_users.set([comped])
    return stats


@pytest.mark.django_db()
class TestRecountPayingUsers:
    @pytest.fixture()
    def users(self):
        plan = ProfessionalPlanFactory()
        users = {}
        for name, amount, label in [
            ("paying", 2000, "standard"),
            ("comped", 0, "comped"),
        ]:
            user = users[name] = UserFactory()
            organization = OrganizationFactory()
            MembershipFactory(user=user, organization=organization)
            SubscriptionItemFactory(
                subscription__organization=organization,
                plan=plan,
                plan_price=PlanPriceFactory(plan=plan, amount=amount, label=label),
            )
        return users

    def test_rows_since_the_date_are_recounted(self, users):
        before = _stats(date(2026, 10, 14), users["comped"])
        after = _stats(date(2026, 10, 15), users["comped"])

        call_command("recount_paying_users", "--since", "2026-10-15")

        after.refresh_from_db()
        assert (after.total_users_pro, after.total_users_org) == (1, 0)
        assert list(after.pro_users.all()) == [users["paying"]]
        before.refresh_from_db()
        assert (before.total_users_pro, before.total_users_org) == (2, 5)
        assert list(before.pro_users.all()) == [users["comped"]]

    def test_a_dry_run_writes_nothing(self, users):
        stats = _stats(date(2026, 10, 15), users["comped"])

        call_command("recount_paying_users", "--since", "2026-10-15", "--dry-run")

        stats.refresh_from_db()
        assert (stats.total_users_pro, stats.total_users_org) == (2, 5)
        assert list(stats.pro_users.all()) == [users["comped"]]
