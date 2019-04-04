# Third Party
from pytest_factoryboy import register

# Squarelet
from squarelet.organizations.tests.factories import (
    FreePlanFactory,
    OrganizationPlanFactory,
    ProfessionalPlanFactory,
)

# Local
from .factories import UserFactory

register(UserFactory)
register(FreePlanFactory)
register(ProfessionalPlanFactory)
register(OrganizationPlanFactory)
