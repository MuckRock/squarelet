# Third Party
import pytest

# Squarelet
from squarelet.organizations import signals
from squarelet.organizations.models.payment import Charge
from squarelet.organizations.tests.factories import OrganizationFactory


@pytest.mark.django_db
def test_charge_unhides_individual_org(user_factory):
    """Creating a charge for an individual org should set hidden=False"""
    user = user_factory()
    org = user.individual_organization
    assert org.hidden is True

    signals.charge_created(
        sender=Charge, instance=Charge(organization=org), created=True
    )

    org.refresh_from_db()
    assert org.hidden is False


@pytest.mark.django_db
def test_charge_does_not_unhide_group_org():
    """Creating a charge for a non-individual org should not change hidden"""
    org = OrganizationFactory(individual=False, hidden=True)

    signals.charge_created(
        sender=Charge, instance=Charge(organization=org), created=True
    )

    org.refresh_from_db()
    assert org.hidden is True
