# Django
from django.conf import settings

# Standard Library
import uuid

# Third Party
import pytest
import requests

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
    def test_create_contact(self, mocker, user):
        """Test the create_contact function using Contacts API v4"""
        contact_id = str(uuid.uuid4())
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"contact": {"id": contact_id}}
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        contact_id_ = create_contact(headers, user.individual_organization, user)
        assert contact_id == contact_id_

        # Verify the request structure matches Contacts API v4
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://www.wixapis.com/contacts/v4/contacts"
        request_json = call_args[1]["json"]
        assert "info" in request_json
        # Verify we're sending the expected payload to the endpoint
        info = request_json["info"]
        assert info["name"]["first"] == user.name.split(" ", 1)[0]
        assert info["name"]["last"] == user.name.split(" ", 1)[1]
        assert info["emails"]["items"][0]["email"] == user.email
        assert info["emails"]["items"][0]["tag"] == "MAIN"
        assert info["company"] == user.individual_organization.name

    @pytest.mark.django_db()
    def test_create_contact_single_word_name(self, mocker, user_factory):
        """Test create_contact handles single-word names correctly"""
        user = user_factory(name="Madonna")
        contact_id = str(uuid.uuid4())
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"contact": {"id": contact_id}}
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        contact_id_ = create_contact(headers, user.individual_organization, user)
        assert contact_id == contact_id_

        # Verify single-word name is handled
        request_json = mock_post.call_args[1]["json"]
        info = request_json["info"]
        assert info["name"]["first"] == "Madonna"
        assert info["name"]["last"] == ""

    def test_get_contact_by_email_v4(self, mocker):
        """Test the get_contact_by_email_v4 function using Contacts API v4"""
        contact_id = str(uuid.uuid4())
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"contacts": [{"id": contact_id}]}
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        email = "info@muckrock.com"
        contact_id_ = get_contact_by_email_v4(headers, email)
        assert contact_id == contact_id_

        # Verify the query filter structure
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "query": {"filter": {"info.emails.email": email}}
        }

    def test_get_contact_by_email_v4_not_found(self, mocker):
        """Test get_contact_by_email_v4 returns None when contact not found"""
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"contacts": []}
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        mocker.patch("requests.post", return_value=mock_response)

        headers = {
            "Authorization": settings.WIX_APP_SECRET,
            "wix-site-id": settings.WIX_SITE_ID,
        }
        email = "nonexistent@example.com"
        contact_id = get_contact_by_email_v4(headers, email)
        assert contact_id is None

    @pytest.mark.django_db()
    def test_add_to_waitlist_new_contact(self, mocker, user):
        """Test add_to_waitlist creates new contact and applies labels"""
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(slug="sunlight-basic-monthly", name="Sunlight Basic")

        # Create mock responses for each API call
        query_response = mocker.Mock()
        query_response.json.return_value = {"contacts": []}
        query_response.raise_for_status.return_value = None
        query_response.status_code = 200

        create_response = mocker.Mock()
        create_response.json.return_value = {"contact": {"id": contact_id}}
        create_response.raise_for_status.return_value = None
        create_response.status_code = 200

        labels_response = mocker.Mock()
        labels_response.json.return_value = {"contact": {"id": contact_id}}
        labels_response.raise_for_status.return_value = None
        labels_response.status_code = 200

        # Mock requests.post to return different responses based on URL
        def mock_post_side_effect(url, **kwargs):
            if "query" in url:
                return query_response
            elif "/labels" in url:
                return labels_response
            else:
                return create_response

        mock_post = mocker.patch("requests.post", side_effect=mock_post_side_effect)

        add_to_waitlist(user.individual_organization, plan, user)

        # Verify all three API calls were made
        assert mock_post.call_count == 3

        # Verify the labels call had correct waitlist labels
        labels_call = [
            call for call in mock_post.call_args_list if "/labels" in str(call)
        ][0]
        assert labels_call[1]["json"] == {
            "labelKeys": ["custom.waitlist", "custom.waitlist-sunlight-basic-monthly"]
        }

    @pytest.mark.django_db()
    def test_add_to_waitlist_existing_contact(self, mocker, user):
        """Test add_to_waitlist uses existing contact and applies labels"""
        contact_id = str(uuid.uuid4())
        plan = PlanFactory(slug="sunlight-premium-annual", name="Sunlight Premium")

        # Mock query to return existing contact
        query_response = mocker.Mock()
        query_response.json.return_value = {"contacts": [{"id": contact_id}]}
        query_response.raise_for_status.return_value = None
        query_response.status_code = 200

        labels_response = mocker.Mock()
        labels_response.json.return_value = {"contact": {"id": contact_id}}
        labels_response.raise_for_status.return_value = None
        labels_response.status_code = 200

        def mock_post_side_effect(url, **kwargs):
            if "query" in url:
                return query_response
            else:
                return labels_response

        mock_post = mocker.patch("requests.post", side_effect=mock_post_side_effect)

        add_to_waitlist(user.individual_organization, plan, user)

        # Verify only two API calls were made (query + labels, no create)
        assert mock_post.call_count == 2

        # Verify labels were added with correct waitlist labels
        labels_call = [
            call for call in mock_post.call_args_list if "/labels" in str(call)
        ][0]
        label_keys = labels_call[1]["json"]["labelKeys"]
        assert "custom.waitlist" in label_keys
        assert any(
            label.startswith("custom.waitlist-sunlight-premium-annual")
            for label in label_keys
        )

    @pytest.mark.django_db()
    def test_add_to_waitlist_handles_errors(self, mocker, user, caplog):
        """Test add_to_waitlist handles API errors gracefully"""
        plan = PlanFactory(slug="sunlight-basic-monthly", name="Sunlight Basic")

        # Mock the query to fail with a RequestException
        mock_response = mocker.Mock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )
        mocker.patch("requests.post", return_value=mock_response)

        # Should not raise an exception, just log the error
        add_to_waitlist(user.individual_organization, plan, user)

        # Verify error was logged
        assert "Failed to add" in caplog.text
        assert user.email in caplog.text
