# Third Party
from pytest_factoryboy import register

# Squarelet
from squarelet.organizations.tests.factories import FreePlanFactory

# Local
from .factories import UserFactory

register(UserFactory)
register(FreePlanFactory)
