# Third Party
import pytest
from pytest_factoryboy import register
from rest_framework.test import APIClient

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    CustomerFactory,
    IndividualOrganizationFactory,
    InvitationFactory,
    MembershipFactory,
    OrganizationFactory,
    OrganizationPlanFactory,
    PlanFactory,
    ProfessionalPlanFactory,
    SubscriptionFactory,
)
from squarelet.users.tests.factories import UserFactory

register(ChargeFactory)
register(PlanFactory)
register(IndividualOrganizationFactory)
register(InvitationFactory)
register(MembershipFactory)
register(OrganizationFactory)
register(OrganizationPlanFactory)
register(ProfessionalPlanFactory)
register(SubscriptionFactory)
register(CustomerFactory)

register(UserFactory)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def client():
    return ClientFactory()
