# Third Party
from pytest_factoryboy import register

# Squarelet
from squarelet.users.tests.factories import UserFactory

# Local
from .factories import (
    ChargeFactory,
    IndividualOrganizationFactory,
    InvitationFactory,
    MembershipFactory,
    OrganizationFactory,
    OrganizationPlanFactory,
    PlanFactory,
    ProfessionalPlanFactory,
    SubscriptionFactory,
)

register(ChargeFactory)
register(PlanFactory)
register(IndividualOrganizationFactory)
register(InvitationFactory)
register(MembershipFactory)
register(OrganizationFactory)
register(OrganizationPlanFactory)
register(ProfessionalPlanFactory)
register(SubscriptionFactory)

register(UserFactory)
