# Third Party
from pytest_factoryboy import register

# Squarelet
from squarelet.users.tests.factories import UserFactory

# Local
from .factories import (
    ChargeFactory,
    FreePlanFactory,
    IndividualOrganizationFactory,
    InvitationFactory,
    MembershipFactory,
    OrganizationFactory,
    OrganizationPlanFactory,
    ProfessionalPlanFactory,
)

register(ChargeFactory)
register(FreePlanFactory)
register(IndividualOrganizationFactory)
register(InvitationFactory)
register(MembershipFactory)
register(OrganizationFactory)
register(OrganizationPlanFactory)
register(ProfessionalPlanFactory)

register(UserFactory)
