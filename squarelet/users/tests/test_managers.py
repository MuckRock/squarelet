# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)
from squarelet.users.models import User
from squarelet.users.tests.factories import UserFactory


class TestGetSearchable:
    """Tests for UserManager.get_searchable"""

    @pytest.mark.django_db
    def test_staff_sees_all_users(self):
        """Staff users can see all users regardless of hidden/private status"""
        staff = UserFactory(is_staff=True)
        public_user = UserFactory()
        public_user.individual_organization.hidden = False
        public_user.individual_organization.private = False
        public_user.individual_organization.save()

        hidden_user = UserFactory()
        # hidden_user.individual_organization.hidden defaults to True

        private_user = UserFactory()
        private_user.individual_organization.hidden = False
        private_user.individual_organization.private = True
        private_user.individual_organization.save()

        results = User.objects.get_searchable(staff)
        assert public_user in results
        assert hidden_user in results
        assert private_user in results

    @pytest.mark.django_db
    def test_hidden_users_excluded(self):
        """Hidden users are never visible to non-staff"""
        searcher = UserFactory()
        hidden_user = UserFactory()
        # hidden_user.individual_organization.hidden defaults to True

        results = User.objects.get_searchable(searcher)
        assert hidden_user not in results

    @pytest.mark.django_db
    def test_public_users_visible(self):
        """Public, non-hidden users are visible to everyone"""
        searcher = UserFactory()
        public_user = UserFactory()
        public_user.individual_organization.hidden = False
        public_user.individual_organization.private = False
        public_user.individual_organization.save()

        results = User.objects.get_searchable(searcher)
        assert public_user in results

    @pytest.mark.django_db
    def test_private_users_visible_to_orgmates(self):
        """Private users are visible to members of shared organizations"""
        searcher = UserFactory()
        private_user = UserFactory()
        private_user.individual_organization.hidden = False
        private_user.individual_organization.private = True
        private_user.individual_organization.save()

        # Not visible before sharing an org
        results = User.objects.get_searchable(searcher)
        assert private_user not in results

        # Add both to the same org
        shared_org = OrganizationFactory(name="Shared Org")
        MembershipFactory(user=searcher, organization=shared_org)
        MembershipFactory(user=private_user, organization=shared_org)

        results = User.objects.get_searchable(searcher)
        assert private_user in results

    @pytest.mark.django_db
    def test_private_users_not_visible_to_strangers(self):
        """Private users are not visible to users who share no organizations"""
        searcher = UserFactory()
        private_user = UserFactory()
        private_user.individual_organization.hidden = False
        private_user.individual_organization.private = True
        private_user.individual_organization.save()

        results = User.objects.get_searchable(searcher)
        assert private_user not in results

    @pytest.mark.django_db
    def test_no_duplicate_results(self):
        """Users sharing multiple orgs with searcher appear only once"""
        searcher = UserFactory()
        other_user = UserFactory()
        other_user.individual_organization.hidden = False
        other_user.individual_organization.private = False
        other_user.individual_organization.save()

        org1 = OrganizationFactory(name="Org A")
        org2 = OrganizationFactory(name="Org B")
        MembershipFactory(user=searcher, organization=org1)
        MembershipFactory(user=other_user, organization=org1)
        MembershipFactory(user=searcher, organization=org2)
        MembershipFactory(user=other_user, organization=org2)

        results = User.objects.get_searchable(searcher)
        assert list(results.filter(pk=other_user.pk)).count(other_user) == 1
