# Django
from django.utils import timezone

# Third Party
import pytest


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
