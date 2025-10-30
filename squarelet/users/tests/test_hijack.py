# Django
from django.contrib.auth.models import Group

# Third Party
import pytest

# Squarelet
from squarelet.users.hijack import hijack_by_group


@pytest.mark.django_db()
class TestHijackByGroup:
    """Test the hijack permission function"""

    def test_normal_user(self, user_factory):
        """Non-staff may not hijack other users"""
        hijacker = user_factory()
        hijacked = user_factory()
        assert not hijack_by_group(hijacker, hijacked)

    def test_inactive_user(self, user_factory):
        """Cannot hijack inactive users"""
        hijacker = user_factory(is_superuser=True)
        hijacked = user_factory(is_active=False)
        assert not hijack_by_group(hijacker, hijacked)

    def test_superuser_hijacker(self, user_factory):
        """Superusers can hijack any active user"""
        hijacker = user_factory(is_superuser=True)
        hijacked = user_factory()
        assert hijack_by_group(hijacker, hijacked)

    def test_superuser_hijacker_can_hijack_superuser(self, user_factory):
        """Superusers can hijack other superusers"""
        hijacker = user_factory(is_superuser=True)
        hijacked = user_factory(is_superuser=True)
        assert hijack_by_group(hijacker, hijacked)

    def test_non_superuser_cannot_hijack_superuser(self, user_factory):
        """Non-superusers cannot hijack superusers"""
        hijacker = user_factory(is_staff=True)
        hijacked = user_factory(is_superuser=True)
        support_group = Group.objects.create(name="Support")
        hijacker.groups.add(support_group)
        assert not hijack_by_group(hijacker, hijacked)

    def test_staff_in_support_group(self, user_factory):
        """Staff in Support group can hijack regular users"""
        hijacker = user_factory(is_staff=True)
        hijacked = user_factory()
        support_group = Group.objects.create(name="Support")
        hijacker.groups.add(support_group)
        assert hijack_by_group(hijacker, hijacked)

    def test_staff_in_technology_group(self, user_factory):
        """Staff in Technology group can hijack regular users"""
        hijacker = user_factory(is_staff=True)
        hijacked = user_factory()
        tech_group = Group.objects.create(name="Technology")
        hijacker.groups.add(tech_group)
        assert hijack_by_group(hijacker, hijacked)

    def test_staff_not_in_hijack_groups(self, user_factory):
        """Staff not in Support or Technology cannot hijack"""
        hijacker = user_factory(is_staff=True)
        hijacked = user_factory()
        other_group = Group.objects.create(name="Other")
        hijacker.groups.add(other_group)
        assert not hijack_by_group(hijacker, hijacked)

    def test_non_staff_in_support_group(self, user_factory):
        """Non-staff in Support group cannot hijack"""
        hijacker = user_factory(is_staff=False)
        hijacked = user_factory()
        support_group = Group.objects.create(name="Support")
        hijacker.groups.add(support_group)
        assert not hijack_by_group(hijacker, hijacked)
