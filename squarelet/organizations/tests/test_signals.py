# Third Party
import pytest

# Squarelet
from squarelet.organizations import signals
from squarelet.organizations.models.payment import Charge, EntitlementGrant
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    EntitlementGrantFactory,
    OrganizationFactory,
)


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
def test_charge_unhides_group_org():
    """Creating a charge for a non-individual org should also change hidden"""
    org = OrganizationFactory(individual=False, hidden=True)

    signals.charge_created(
        sender=Charge, instance=Charge(organization=org), created=True
    )

    org.refresh_from_db()
    assert org.hidden is False


def _broadcast_uuids(mock_send):
    """Collect all UUIDs broadcast across all calls to send_cache_invalidations."""
    uuids = set()
    for call in mock_send.call_args_list:
        assert call.args[0] == "organization"
        uuids.update(str(u) for u in call.args[1])
    return uuids


class TestEntitlementGrantSignals:
    """Tests for admin-driven cache invalidation on EntitlementGrant changes."""

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_create_with_explicit_orgs(
        self, mocker, django_capture_on_commit_callbacks
    ):
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        org = OrganizationFactory()
        with django_capture_on_commit_callbacks(execute=True):
            EntitlementGrantFactory(organizations=[org])
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_active_toggle_off(
        self, mocker, django_capture_on_commit_callbacks
    ):
        org = OrganizationFactory()
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory(organizations=[org])
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.active = False
            grant.save()
        # Toggling off must still broadcast the org that previously matched.
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_active_toggle_on(
        self, mocker, django_capture_on_commit_callbacks
    ):
        org = OrganizationFactory()
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory(organizations=[org], active=False)
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.active = True
            grant.save()
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_org_added_to_m2m(
        self, mocker, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory()
        org = OrganizationFactory()
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.organizations.add(org)
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_org_removed_from_m2m(
        self, mocker, django_capture_on_commit_callbacks
    ):
        org = OrganizationFactory()
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory(organizations=[org])
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.organizations.remove(org)
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_entitlements_changed(
        self, mocker, django_capture_on_commit_callbacks
    ):
        org = OrganizationFactory()
        entitlement = EntitlementFactory()
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory(organizations=[org])
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.entitlements.add(entitlement)
        assert str(org.uuid) in _broadcast_uuids(mock_send)

    @pytest.mark.django_db(transaction=True)
    def test_invalidates_on_delete(self, mocker, django_capture_on_commit_callbacks):
        org = OrganizationFactory()
        with django_capture_on_commit_callbacks(execute=True):
            grant = EntitlementGrantFactory(organizations=[org])
        mock_send = mocker.patch(
            "squarelet.organizations.signals.send_cache_invalidations"
        )
        with django_capture_on_commit_callbacks(execute=True):
            grant.delete()
        assert str(org.uuid) in _broadcast_uuids(mock_send)
        assert not EntitlementGrant.objects.filter(pk=grant.pk).exists()
