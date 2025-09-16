# Django
from django.conf import settings

# Standard Library
import uuid

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import PlanFactory
from squarelet.organizations.wix import (
    add_labels,
    create_member,
    get_contact_by_email,
    send_set_password_email,
    sync_wix,
)


class TestWix:

    def test_get_contact_by_email(self, requests_mock):
        """Test the get_contact_by_email function"""
        contact_id = str(uuid.uuid4())
        requests_mock.post(
            "https://www.wixapis.com/members/v1/members/query",
            json={"members": [{"contactId": contact_id}], "metadata": {"count": 1}},
        )
        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        email = "info@muckrock.com"
        contact_id_ = get_contact_by_email(headers, email)
        assert contact_id == contact_id_

    @pytest.mark.django_db()
    def test_create_member(self, requests_mock, user):
        """Test the create_member function"""
        contact_id = str(uuid.uuid4())
        requests_mock.post(
            "https://www.wixapis.com/members/v1/members",
            json={"member": {"contactId": contact_id}},
        )
        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        contact_id_ = create_member(headers, user.individual_organization, user)
        assert contact_id == contact_id_

    @pytest.mark.django_db()
    def test_add_labels(self, requests_mock):
        """Test the add_labels function"""
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(name="Sunlight Premium")
        requests_mock.post(
            f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
            json={"contact": {"id": contact_id}},
        )
        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        add_labels(headers, contact_id, plan)

    def test_send_set_password_email(self, requests_mock):
        """Test the send_set_password_email function"""
        requests_mock.post(
            "https://www.wixapis.com/wix-sm/api/v1/auth/v1/auth/members"
            "/send-set-password-email",
            json={"accepted": True},
        )
        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        send_set_password_email(headers, "info@muckrock.com")

    @pytest.mark.django_db()
    def test_sync_wix(self, requests_mock, user):
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(name="Sunlight Premium")
        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }

        requests_mock.post(
            "https://www.wixapis.com/members/v1/members/query",
            json={"metadata": {"count": 0}},
        )
        requests_mock.post(
            "https://www.wixapis.com/members/v1/members",
            json={"member": {"contactId": contact_id}},
        )
        requests_mock.post(
            f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
            json={"contact": {"id": contact_id}},
        )
        requests_mock.post(
            "https://www.wixapis.com/wix-sm/api/v1/auth/v1/auth/members"
            "/send-set-password-email",
            json={"accepted": True},
        )

        sync_wix(user.individual_organization, plan, user)
