# Django
from django.test import TestCase

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Membership
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)
from squarelet.users.tests.factories import UserFactory

# pylint: disable=invalid-name,too-many-public-methods,protected-access


class TestMembershipQuerySet(TestCase):
    """Unit tests for Membership queryset"""

    @pytest.mark.django_db
    def test_get_viewable(self):
        admin, member, user = UserFactory.create_batch(3)
        private_org = OrganizationFactory(admins=[admin], private=True)
        MembershipFactory(organization=private_org, user=member)

        assert Membership.objects.get_viewable(member).count() == 3
        assert Membership.objects.get_viewable(user).count() == 1

        another_user = UserFactory()
        assert member.memberships.get_viewable(another_user).count() == 0
