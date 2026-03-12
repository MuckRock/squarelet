# Standard Library
from unittest.mock import PropertyMock

# Third Party
import pytest
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.organizations.models.payment import Charge
from squarelet.organizations.tests.factories import OrganizationFactory
from squarelet.users import signals


def test_email_confirmed(user_factory, mocker):
    mocked = mocker.patch("squarelet.users.signals.send_cache_invalidations")
    user = user_factory.build()
    email = EmailAddress(user=user, primary=True)
    signals.email_confirmed(None, email)
    mocked.assert_called_with("user", user.uuid)


@pytest.mark.django_db
def test_email_confirmed_unhides_user(user_factory, mocker):
    """Confirming a primary email should set hidden=False on the individual org"""
    mocker.patch("squarelet.users.signals.send_cache_invalidations")
    user = user_factory()
    assert user.individual_organization.hidden is True

    email = EmailAddress.objects.get(user=user)
    email.primary = True
    email.save()

    signals.email_confirmed(None, email)

    user.individual_organization.refresh_from_db()
    assert user.individual_organization.hidden is False


@pytest.mark.django_db
def test_email_confirmed_nonprimary_does_not_unhide(user_factory, mocker):
    """Confirming a non-primary email should not change hidden status"""
    mocker.patch("squarelet.users.signals.send_cache_invalidations")
    user = user_factory()
    email = EmailAddress.objects.create(
        user=user, email="secondary@example.com", primary=False, verified=True
    )

    signals.email_confirmed(None, email)

    user.individual_organization.refresh_from_db()
    assert user.individual_organization.hidden is True


@pytest.mark.django_db
def test_charge_unhides_individual_org(user_factory):
    """Creating a charge for an individual org should set hidden=False"""
    user = user_factory()
    org = user.individual_organization
    assert org.hidden is True

    signals.charge_created(
        sender=Charge, instance=Charge(organization=org), created=True
    )

    org.refresh_from_db()
    assert org.hidden is False


@pytest.mark.django_db
def test_charge_does_not_unhide_group_org():
    """Creating a charge for a non-individual org should not change hidden"""
    org = OrganizationFactory(individual=False, hidden=True)

    signals.charge_created(
        sender=Charge, instance=Charge(organization=org), created=True
    )

    org.refresh_from_db()
    assert org.hidden is True


@pytest.mark.django_db(transaction=True)
def test_email_changed(user_factory, mocker, mailoutbox):
    mocked_cache_inv = mocker.patch("squarelet.users.signals.send_cache_invalidations")
    mocked_customer = mocker.patch(
        "squarelet.organizations.models.Customer.stripe_customer",
        new_callable=PropertyMock,
    )
    user = user_factory(email_failed=True)

    user.individual_organization.customer().stripe_customer = mocked_customer

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
