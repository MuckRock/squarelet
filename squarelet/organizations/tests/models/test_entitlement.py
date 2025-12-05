# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import EntitlementFactory, PlanFactory


class TestEntitlement:
    """Unit tests for Entitlement model"""

    @pytest.mark.django_db()
    def test_public(self):
        public_plan = PlanFactory()
        private_plan = PlanFactory(public=False)
        entitlement = EntitlementFactory()

        assert not entitlement.public

        entitlement.plans.set([private_plan])
        assert not entitlement.public

        entitlement.plans.set([public_plan])
        assert entitlement.public

        entitlement.plans.set([private_plan, public_plan])
        assert entitlement.public
