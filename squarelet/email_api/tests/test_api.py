# Third Party
import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from rest_framework import status

# Squarelet
from squarelet.email_api.tests.factories import EmailFactory


@pytest.mark.django_db()
class TestPPEmailAPI:
    def test_list(self, api_client, user):
        """List emails for user"""
        emails_for_user = 10
        emails_for_other_users = 5
        api_client.force_authenticate(user=user)
        EmailFactory.create_batch(emails_for_user, user=user)
        EmailFactory.create_batch(emails_for_other_users)
        response = api_client.get("/pp-api/emails/")
        assert response.status_code == status.HTTP_200_OK
        response_json = response.json()
        assert len(response_json["results"]) == emails_for_user

    def test_update(self, api_client, user, mocker):
        api_client.force_authenticate(user=user)
        primary_email = EmailFactory(
            email="primary@gmail.com", user=user, primary=True, verified=True
        )
        secondary_email = EmailFactory(
            email="secondary@gmail.com", user=user, primary=False, verified=True
        )
        mocker.patch(
            "squarelet.organizations.models.Organization.customer", default_source=None
        )
        response = api_client.patch(
            f"/pp-api/emails/{secondary_email.email}/",
            {"email": "secondary@gmail.com", "primary": True},
        )
        assert response.status_code == status.HTTP_200_OK
        secondary_email.refresh_from_db()
        assert secondary_email.primary
        primary_email.refresh_from_db()
        assert not primary_email.primary

    def test_update_bad(self, api_client, user, mocker):
        api_client.force_authenticate(user=user)
        EmailFactory(email="primary@gmail.com", user=user, primary=True, verified=True)
        secondary_email = EmailFactory(
            email="secondary@gmail.com", user=user, primary=False, verified=False
        )
        mocker.patch(
            "squarelet.organizations.models.Organization.customer", default_source=None
        )
        response = api_client.patch(
            f"/pp-api/emails/{secondary_email.email}/",
            {"email": "secondary@gmail.com", "primary": True},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create(self, api_client, user):
        api_client.force_authenticate(user=user)
        test_email_address = "apicreated@gmail.com"
        response = api_client.post("/pp-api/emails/", {"email": test_email_address})
        assert response.status_code == status.HTTP_201_CREATED
        response_json = response.json()
        assert response_json["email"] == test_email_address
        assert response_json["verified"] is False
        assert response_json["primary"] is False

    def test_destroy(self, api_client, user):
        api_client.force_authenticate(user=user)
        primary_email = EmailFactory(email="primary@gmail.com", user=user, primary=True)
        secondary_email = EmailFactory(
            email="secondary@gmail.com", user=user, primary=False
        )
        response = api_client.delete(f"/pp-api/emails/{secondary_email.email}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        emails = EmailAddress.objects.filter(user=user)
        assert len(emails) == 1
        assert emails.first() == primary_email


@pytest.mark.django_db()
class TestPPEmailConfirmationAPI:
    def test_update(self, api_client, user, mocker):
        api_client.force_authenticate(user=user)
        unverified_email = EmailFactory(
            email="sketchy@gmail.com", user=user, verified=False
        )
        confirmation = EmailConfirmationHMAC(unverified_email)
        mocker.patch(
            "squarelet.organizations.models.Organization.customer", default_source=None
        )
        response = api_client.patch(
            f"/pp-api/verify/{confirmation.key}/", {"verified": True}
        )
        assert response.status_code == status.HTTP_200_OK
        unverified_email.refresh_from_db()
        assert unverified_email.verified
