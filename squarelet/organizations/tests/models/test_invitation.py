# Django
from django.core.exceptions import ValidationError
from django.utils import timezone

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import RelationshipType


class TestInvitation:
    """Unit tests for Invitation model"""

    def test_str(self, invitation_factory):
        invitation = invitation_factory.build()
        assert str(invitation) == f"Invitation: {invitation.uuid}"

    def test_send(self, invitation_factory, mailoutbox):
        invitation = invitation_factory.build()
        invitation.send()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert mail.subject == f"Invitation to join {invitation.organization.name}"
        assert mail.to == [invitation.email]

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_with_user(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        invitation.user = user_factory()
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_without_user(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        user = user_factory()
        assert invitation.user is None
        invitation.accept(user)
        assert invitation.user == user
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.django_db()
    def test_accept_missing_user(self, invitation_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory.build()
        assert invitation.user is None
        with pytest.raises(ValueError):
            invitation.accept()

    @pytest.mark.django_db()
    def test_accept_closed(self, invitation_factory, user_factory, mocker):
        mocker.patch("stripe.Plan.create")
        user = user_factory.build()
        invitation = invitation_factory.build(accepted_at=timezone.now())
        with pytest.raises(ValueError):
            invitation.accept(user)

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_duplicate(
        self, invitation_factory, user_factory, membership_factory, mocker
    ):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        invitation.user = user_factory()
        membership_factory(organization=invitation.organization, user=invitation.user)
        assert invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_verified(self, invitation_factory, user_factory, mocker):
        mocked = mocker.patch("squarelet.core.utils.mailchimp_journey")
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory(organization__verified_journalist=True)
        invitation.user = user_factory()
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()
        # In test environments, MailChimp calls are skipped
        assert mocked.call_count == 0

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_verified_verified(self, invitation_factory, user_factory, mocker):
        mocked = mocker.patch(
            "squarelet.organizations.models.organization.mailchimp_journey"
        )
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory(organization__verified_journalist=True)
        invitation.user = user_factory(
            individual_organization__verified_journalist=True
        )
        assert not invitation.organization.has_member(invitation.user)
        invitation.accept()
        assert invitation.organization.has_member(invitation.user)
        assert invitation.accepted_at == timezone.now()
        mocked.assert_not_called()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_reject(self, invitation_factory, mocker):
        mocker.patch("stripe.Plan.create")
        invitation = invitation_factory()
        invitation.reject()
        assert invitation.rejected_at == timezone.now()

    def test_reject_closed(self, invitation_factory):
        invitation = invitation_factory.build(rejected_at=timezone.now())
        with pytest.raises(ValueError):
            invitation.reject()

    def test_get_name_no_user(self, invitation_factory):
        invitation = invitation_factory.build()
        assert invitation.get_name() == invitation.email

    def test_get_name_user(self, invitation_factory, user_factory):
        invitation = invitation_factory.build()
        invitation.user = user_factory.build()
        assert invitation.get_name() == f"{invitation.user.name} ({invitation.email})"


class TestOrganizationInvitation:
    """Unit tests for OrganizationInvitation model"""

    def test_str(self, organization_invitation_factory):
        invitation = organization_invitation_factory.build()
        assert str(invitation) == (
            f"Invitation to {invitation.to_organization} by "
            f"{invitation.from_organization}"
        )

    @pytest.mark.django_db()
    def test_clean_valid_invitation(self, organization_invitation_factory):
        """Test that clean passes for valid invitation"""
        from_org = organization_invitation_factory.create(
            from_organization__collective_enabled=True
        )
        invitation = organization_invitation_factory.build(
            from_organization=from_org.from_organization,
            relationship_type=RelationshipType.member,
        )
        # Should not raise
        invitation.clean()

    @pytest.mark.django_db()
    def test_clean_from_org_not_collective(self, organization_invitation_factory):
        """Test that clean fails if from_organization doesn't have collective_enabled"""

        invitation = organization_invitation_factory.build(
            from_organization__collective_enabled=False,
            relationship_type=RelationshipType.member,
        )
        with pytest.raises(ValidationError):
            invitation.clean()

    @pytest.mark.django_db()
    def test_clean_child_relationship_parent_check(
        self, organization_invitation_factory
    ):
        """Test that clean validates from_org collective_enabled for child
        relationships"""

        invitation = organization_invitation_factory.build(
            from_organization__collective_enabled=False,
            relationship_type=RelationshipType.child,
        )
        with pytest.raises(ValidationError):
            invitation.clean()

    @pytest.mark.django_db()
    def test_is_pending(self, organization_invitation_factory):
        """Test is_pending property"""
        invitation = organization_invitation_factory()
        assert invitation.is_pending

        invitation.accepted_at = timezone.now()
        assert not invitation.is_pending

        invitation.accepted_at = None
        invitation.rejected_at = timezone.now()
        assert not invitation.is_pending

    @pytest.mark.django_db()
    def test_is_accepted(self, organization_invitation_factory):
        """Test is_accepted property"""
        invitation = organization_invitation_factory()
        assert not invitation.is_accepted

        invitation.accepted_at = timezone.now()
        invitation.save()
        assert invitation.is_accepted

    @pytest.mark.django_db()
    def test_is_rejected(self, organization_invitation_factory):
        """Test is_rejected property"""
        invitation = organization_invitation_factory()
        assert not invitation.is_rejected

        invitation.rejected_at = timezone.now()
        invitation.save()
        assert invitation.is_rejected

    @pytest.mark.django_db()
    def test_send(self, user_factory, organization_invitation_factory, mailoutbox):
        """Test sending invitation emails"""
        user = user_factory()
        invitation = organization_invitation_factory(
            request=False, to_organization__admins=[user]
        )
        invitation.send()
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert invitation.from_organization.name in mail.subject

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_member_invitation(self, organization_invitation_factory):
        """Test accepting a member invitation"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True,
            relationship_type=RelationshipType.member,
        )
        from_org = invitation.from_organization
        to_org = invitation.to_organization

        assert not from_org.members.filter(pk=to_org.pk).exists()

        invitation.accept()

        assert from_org.members.filter(pk=to_org.pk).exists()
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_accept_child_invitation(self, organization_invitation_factory):
        """Test accepting a child invitation"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True,
            relationship_type=RelationshipType.child,
        )
        from_org = invitation.from_organization
        to_org = invitation.to_organization

        assert to_org.parent is None

        invitation.accept()

        to_org.refresh_from_db()
        assert to_org.parent == from_org
        assert invitation.accepted_at == timezone.now()

    @pytest.mark.django_db()
    def test_accept_closed_invitation(self, organization_invitation_factory):
        """Test that accepting an already accepted invitation raises error"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True, accepted_at=timezone.now()
        )
        with pytest.raises(
            ValueError, match="This invitation has already been processed"
        ):
            invitation.accept()

    @pytest.mark.django_db()
    def test_accept_rejected_invitation(self, organization_invitation_factory):
        """Test that accepting a rejected invitation raises error"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True, rejected_at=timezone.now()
        )
        with pytest.raises(
            ValueError, match="This invitation has already been processed"
        ):
            invitation.accept()

    @pytest.mark.freeze_time
    @pytest.mark.django_db()
    def test_reject(self, organization_invitation_factory):
        """Test rejecting an invitation"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True
        )
        invitation.reject()
        assert invitation.rejected_at == timezone.now()

    @pytest.mark.django_db()
    def test_reject_closed_invitation(self, organization_invitation_factory):
        """Test that rejecting an already rejected invitation raises error"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True, rejected_at=timezone.now()
        )
        with pytest.raises(
            ValueError, match="This invitation has already been processed"
        ):
            invitation.reject()

    @pytest.mark.django_db()
    def test_reject_accepted_invitation(self, organization_invitation_factory):
        """Test that rejecting an accepted invitation raises error"""
        invitation = organization_invitation_factory(
            from_organization__collective_enabled=True, accepted_at=timezone.now()
        )
        with pytest.raises(
            ValueError, match="This invitation has already been processed"
        ):
            invitation.reject()
