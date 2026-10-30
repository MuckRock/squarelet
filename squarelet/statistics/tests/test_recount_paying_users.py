# Django
from django.core.management import call_command

# Standard Library
from datetime import date
from io import StringIO

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    OrganizationPlanFactory,
    PlanPriceFactory,
    ProfessionalPlanFactory,
    SubscriptionItemFactory,
)
from squarelet.statistics.models import Statistics
from squarelet.users.tests.factories import UserFactory

SINCE = date(2026, 10, 15)


def _line(user, plan, amount):
    organization = OrganizationFactory()
    MembershipFactory(user=user, organization=organization)
    SubscriptionItemFactory(
        subscription__organization=organization,
        plan=plan,
        plan_price=plan.prices.filter(amount=amount).first()
        or PlanPriceFactory(
            plan=plan, amount=amount, label="comped" if amount == 0 else "standard"
        ),
    )


def _stats(day, pro_users, org=50):
    stats = Statistics.objects.create(
        date=day,
        total_users=0,
        total_users_excluding_agencies=0,
        total_users_pro=len(pro_users),
        total_users_org=org,
        total_users_mfa=0,
        total_orgs=0,
        verified_orgs=0,
    )
    stats.pro_users.set(pro_users)
    return stats


def _recount(*args):
    out = StringIO()
    call_command(
        "recount_paying_users", "--since", SINCE.isoformat(), *args, stdout=out
    )
    return out.getvalue()


@pytest.mark.django_db()
class TestRecountPayingUsers:
    """Comps come out of each row; the day's real changes stay."""

    @pytest.fixture()
    def users(self):
        professional = ProfessionalPlanFactory()
        organization = OrganizationPlanFactory()
        users = {name: UserFactory() for name in ["paying", "comped", "lapsed"]}
        _line(users["paying"], professional, 2000)
        _line(users["comped"], professional, 0)
        # One comped and one paying org member: the old count saw two.
        _line(UserFactory(), organization, 0)
        _line(UserFactory(), organization, 10000)
        return users

    def _assert_row(self, stats, pro_users, org):
        stats.refresh_from_db()
        assert set(stats.pro_users.all()) == set(pro_users)
        assert (stats.total_users_pro, stats.total_users_org) == (len(pro_users), org)

    def test_comps_leave_and_each_days_users_stay(self, users):
        stats = _stats(SINCE, [users["paying"], users["comped"], users["lapsed"]])

        _recount()

        self._assert_row(stats, [users["paying"], users["lapsed"]], 49)

    def test_rows_before_the_date_are_untouched(self, users):
        stats = _stats(date(2026, 10, 14), [users["paying"], users["comped"]])

        _recount()

        self._assert_row(stats, [users["paying"], users["comped"]], 50)

    def test_a_second_run_changes_nothing(self, users):
        stats = _stats(SINCE, [users["paying"], users["comped"]])

        _recount()
        _recount()

        self._assert_row(stats, [users["paying"]], 49)

    def test_a_row_without_comps_is_left_alone(self, users):
        stats = _stats(SINCE, [users["paying"]])

        _recount()

        self._assert_row(stats, [users["paying"]], 50)

    def test_a_dry_run_writes_nothing(self, users):
        stats = _stats(SINCE, [users["paying"], users["comped"]])

        _recount("--dry-run")

        self._assert_row(stats, [users["paying"], users["comped"]], 50)

    def test_a_date_with_no_rows_says_so(self, users):
        _stats(date(2026, 10, 14), [users["paying"], users["comped"]])

        assert "No statistics stored" in _recount()
