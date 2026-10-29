# Standard Library
from datetime import date, timedelta

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
from squarelet.users.tests.factories import UserFactory

# Local
from .. import tasks
from ..models import Statistics


@pytest.mark.django_db()
def test_store_statistics():
    tasks.store_statistics()
    stats = Statistics.objects.first()
    assert stats.date == date.today() - timedelta(1)
    assert stats.total_users == 0
    assert stats.total_orgs == 0


@pytest.mark.django_db()
class TestPayingUsers:
    """Pro and org counts are paying users: comps share the paid plan's slug."""

    PLANS = {
        "professional": ProfessionalPlanFactory,
        "organization": OrganizationPlanFactory,
    }

    def _line(self, user, slug, amount):
        plan = self.PLANS[slug]()
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

    def test_a_comped_line_is_not_counted(self):
        paying = UserFactory()
        self._line(paying, "professional", 2000)
        self._line(UserFactory(), "professional", 0)
        self._line(UserFactory(), "organization", 0)

        tasks.store_statistics()

        stats = Statistics.objects.get()
        assert stats.total_users_pro == 1
        assert list(stats.pro_users.all()) == [paying]
        assert stats.total_users_org == 0

    def test_a_user_in_two_paying_orgs_counts_once(self):
        user = UserFactory()
        self._line(user, "organization", 10000)
        self._line(user, "organization", 10000)

        tasks.store_statistics()

        assert Statistics.objects.get().total_users_org == 1

    def test_a_paid_line_beside_a_comp_in_another_org_counts(self):
        user = UserFactory()
        self._line(user, "organization", 0)
        self._line(user, "organization", 10000)

        tasks.store_statistics()

        assert Statistics.objects.get().total_users_org == 1

    def test_a_comp_is_not_counted_for_a_user_paying_for_another_plan(self):
        user = UserFactory()
        self._line(user, "professional", 0)
        self._line(user, "organization", 10000)

        tasks.store_statistics()

        stats = Statistics.objects.get()
        assert stats.total_users_pro == 0
        assert stats.total_users_org == 1
