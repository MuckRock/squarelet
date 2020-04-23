# Standard Library
from unittest.mock import PropertyMock

# Third Party
import pytest
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.users import signals
from squarelet.organizations.tests.factories import PressPassCustomerFactory

def test_email_confirmed(user_factory, mocker):
    mocked = mocker.patch("squarelet.users.signals.send_cache_invalidations")
    user = user_factory.build()
    email = EmailAddress(user=user, primary=True)
    signals.email_confirmed(None, email)
    mocked.assert_called_with("user", user.uuid)


@pytest.mark.django_db(transaction=True)
def test_email_changed(user_factory, mocker, mailoutbox):
    mocked_cache_inv = mocker.patch("squarelet.users.signals.send_cache_invalidations")
    mocked_customer = mocker.patch(
        "squarelet.organizations.models.Customer.stripe_customer",
        new_callable=PropertyMock,
    )
    user = user_factory(email_failed=True)
    mocked_presspass_customer = PressPassCustomerFactory(organization=user.individual_organization)

    user.individual_organization.customer(0).stripe_customer = mocked_customer
    user.individual_organization.customer(1).stripe_customer = mocked_presspass_customer

    old_email = EmailAddress(email="old@example.com")
    new_email = EmailAddress(email="new@example.com", user=user)
    signals.email_changed(None, user, old_email, new_email)

    assert mocked_customer().email == new_email.email
    mocked_customer().save.assert_called()
    assert not user.email_failed
    mocked_cache_inv.assert_called_with("user", user.uuid)
    mail = mailoutbox[0]
    assert mail.subject == "Changed email address"
    assert mail.to == [old_email.email]
