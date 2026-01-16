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
    add_to_waitlist,
    create_contact,
    create_member,
    get_contact_by_email,
    get_contact_by_email_v4,
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
        assert requests_mock.last_request.json() == {
            "query": {"filter": {"loginEmail": email}}
        }

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
        assert requests_mock.last_request.json() == {
            "member": {
                "loginEmail": user.email,
                "contact": {
                    "firstName": user.name.split(" ", 1)[0],
                    "lastName": user.name.split(" ", 1)[1],
                    "emails": [user.email],
                    "company": user.individual_organization.name,
                },
            }
        }

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
        assert requests_mock.last_request.json() == {
            "labelKeys": ["custom.paying-member", "custom.premium-member"]
        }

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
        assert requests_mock.last_request.json() == {
            "email": "info@muckrock.com",
            "hideIgnoreMessage": True,
        }

    @pytest.mark.django_db()
    def test_sync_wix(self, requests_mock, user):
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(name="Sunlight Premium")
        urls = []

        url = "https://www.wixapis.com/members/v1/members/query"
        urls.append(url)
        requests_mock.post(
            url,
            json={"metadata": {"count": 0}},
        )
        url = "https://www.wixapis.com/members/v1/members"
        urls.append(url)
        requests_mock.post(
            url,
            json={"member": {"contactId": contact_id}},
        )
        url = (
            "https://www.wixapis.com/wix-sm/api/v1/auth/v1/auth/members"
            "/send-set-password-email"
        )
        urls.append(url)
        requests_mock.post(
            url,
            json={"accepted": True},
        )
        url = f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels"
        urls.append(url)
        requests_mock.post(
            url,
            json={"contact": {"id": contact_id}},
        )

        sync_wix(user.individual_organization, plan, user)

        for url, response in zip(urls, requests_mock.request_history):
            assert response.url == url

    @pytest.mark.django_db()
    def test_create_contact(self, requests_mock, user):
        """Test the create_contact function using Contacts API v4"""
        contact_id = str(uuid.uuid4())
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts",
            json={"contact": {"id": contact_id}},
        )

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        contact_id_ = create_contact(headers, user.individual_organization, user)
        assert contact_id == contact_id_

        # Verify the request structure matches Contacts API v4
        request_json = requests_mock.last_request.json()
        assert "info" in request_json
        # Verify we're sending the expected payload to the endpoint
        info = request_json["info"]
        assert info["name"]["first"] == user.name.split(" ", 1)[0]
        assert info["name"]["last"] == user.name.split(" ", 1)[1]
        assert info["emails"]["items"][0]["email"] == user.email
        assert info["emails"]["items"][0]["tag"] == "MAIN"
        assert info["company"] == user.individual_organization.name

    @pytest.mark.django_db()
    def test_create_contact_single_word_name(self, requests_mock, user_factory):
        """Test create_contact handles single-word names correctly"""
        user = user_factory(name="Madonna")
        contact_id = str(uuid.uuid4())
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts",
            json={"contact": {"id": contact_id}},
        )

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        contact_id_ = create_contact(headers, user.individual_organization, user)
        assert contact_id == contact_id_

        # Verify single-word name is handled
        request_json = requests_mock.last_request.json()
        info = request_json["info"]
        assert info["name"]["first"] == "Madonna"
        assert info["name"]["last"] == ""

    def test_get_contact_by_email_v4(self, requests_mock):
        """Test the get_contact_by_email_v4 function using Contacts API v4"""
        contact_id = str(uuid.uuid4())
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            json={"contacts": [{"id": contact_id}]},
        )

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        email = "info@muckrock.com"
        contact_id_ = get_contact_by_email_v4(headers, email)
        assert contact_id == contact_id_

        # Verify the query filter structure
        assert requests_mock.last_request.json() == {
            "query": {"filter": {"info.emails.email": email}}
        }

    def test_get_contact_by_email_v4_not_found(self, requests_mock):
        """Test get_contact_by_email_v4 returns None when contact not found"""
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            json={"contacts": []},
        )

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        email = "nonexistent@example.com"
        contact_id = get_contact_by_email_v4(headers, email)
        assert contact_id is None

    @pytest.mark.django_db()
    def test_add_to_waitlist_new_contact(self, requests_mock, user):
        """Test add_to_waitlist creates new contact and applies labels"""
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(slug="sunlight-essential-monthly", name="Sunlight Essential")

        # Mock query to return no existing contact
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            json={"contacts": []},
        )
        # Mock create contact
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts",
            json={"contact": {"id": contact_id}},
        )
        # Mock add labels
        requests_mock.post(
            f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
            json={"contact": {"id": contact_id}},
        )

        add_to_waitlist(user.individual_organization, plan, user)

        # Verify all three API calls were made
        assert len(requests_mock.request_history) == 3

        # Verify the labels call had correct waitlist labels
        labels_request = requests_mock.request_history[2]
        assert labels_request.json() == {
            "labelKeys": [
                "custom.waitlist",
                "custom.waitlist-sunlight-essential-monthly",
            ]
        }

    @pytest.mark.django_db()
    def test_add_to_waitlist_existing_contact(self, requests_mock, user):
        """Test add_to_waitlist uses existing contact and applies labels"""
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(slug="sunlight-enhanced-annual", name="Sunlight Enhanced")

        # Mock query to return existing contact
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            json={"contacts": [{"id": contact_id}]},
        )
        # Mock add labels
        requests_mock.post(
            f"https://www.wixapis.com/contacts/v4/contacts/{contact_id}/labels",
            json={"contact": {"id": contact_id}},
        )

        add_to_waitlist(user.individual_organization, plan, user)

        # Verify only two API calls were made (query + labels, no create)
        assert len(requests_mock.request_history) == 2

        # Verify labels were added with correct waitlist labels
        labels_request = requests_mock.request_history[1]
        label_keys = labels_request.json()["labelKeys"]
        assert "custom.waitlist" in label_keys
        assert any(
            label.startswith("custom.waitlist-sunlight-enhanced-annual")
            for label in label_keys
        )

    @pytest.mark.django_db()
    def test_add_to_waitlist_handles_errors(self, requests_mock, user, caplog):
        """Test add_to_waitlist handles API errors gracefully"""
        plan = PlanFactory(slug="sunlight-essential-monthly", name="Sunlight Essential")

        # Mock the query to fail with a 500 error
        requests_mock.post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            status_code=500,
            text="500 Server Error",
        )

        # Should not raise an exception, just log the error
        add_to_waitlist(user.individual_organization, plan, user)

        # Verify error was logged
        assert "Failed to add" in caplog.text
        assert user.email in caplog.text
