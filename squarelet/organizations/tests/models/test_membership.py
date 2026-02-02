# Third Party
import pytest

# Squarelet
from squarelet.organizations.models.membership import Membership

class TestMembership:
    """Unit tests for Membership model"""

    def test_str(self, membership_factory):
        membership = membership_factory.build()
        assert (
            str(membership)
            == f"Membership: {membership.user} in {membership.organization}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_save(self, membership_factory, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.membership.send_cache_invalidations"
        )
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)

    @pytest.mark.django_db(transaction=True)
    def test_save_delete(self, membership_factory, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.membership.send_cache_invalidations"
        )
        membership = membership_factory()
        mocked.assert_called_with("user", membership.user.uuid)
        mocked.reset_mock()
        membership.delete()
        mocked.assert_called_with("user", membership.user.uuid)

    @pytest.mark.django_db(transaction=True)
    def test_save_syncs_new_user_via_group_wix_plan(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Test new membership syncs user via group's Wix plan"""
        mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")
        mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )

        wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[wix_plan]
        )
        member_org = organization_factory()
        group.members.add(member_org)

        user = user_factory()

        Membership.objects.create(user=user, organization=member_org, admin=False)

        # Should sync user via group's plan
        mock_sync.assert_called_once_with(group.pk, wix_plan.pk, user.pk)

    @pytest.mark.django_db(transaction=True)
    def test_save_prefers_direct_wix_plan_over_group(
        self, organization_factory, plan_factory, user_factory, mocker
    ):
        """Test new membership uses direct org Wix plan over group plan"""
        mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")
        mocker.patch(
            "squarelet.organizations.models.organization.send_cache_invalidations"
        )

        group_wix_plan = plan_factory(wix=True)
        org_wix_plan = plan_factory(wix=True)
        group = organization_factory(
            collective_enabled=True, share_resources=True, plans=[group_wix_plan]
        )
        member_org = organization_factory(plans=[org_wix_plan])
        group.members.add(member_org)

        user = user_factory()

        Membership.objects.create(user=user, organization=member_org, admin=False)

        # Should sync user via org's direct plan (not group's)
        mock_sync.assert_called_once_with(member_org.pk, org_wix_plan.pk, user.pk)
