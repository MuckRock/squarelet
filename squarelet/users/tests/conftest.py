# Third Party
from pytest_factoryboy import register

# Squarelet
from squarelet.organizations.tests.factories import (
    OrganizationPlanFactory,
    PlanFactory,
    ProfessionalPlanFactory,
)
from squarelet.users.tests.factories import UserFactory

register(UserFactory)
register(PlanFactory)
register(ProfessionalPlanFactory)
register(OrganizationPlanFactory)
