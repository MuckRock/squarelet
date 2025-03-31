# Standard Library
from urllib.parse import parse_qs, urlsplit

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import (
    EmailDomainFactory,
    OrganizationFactory,
)


def test_str(user_factory):
    user = user_factory.build()
    assert str(user) == user.username


@pytest.mark.django_db(transaction=True)
def test_save(user_factory, mocker):
    mocked = mocker.patch("squarelet.users.models.send_cache_invalidations")
    user = user_factory()
    mocked.assert_called_with("user", user.uuid)


def test_get_absolute_url(user_factory):
    user = user_factory.build()
    assert user.get_absolute_url() == f"/users/{user.username}/"


def test_get_full_name(user_factory):
    user = user_factory.build()
    assert user.get_full_name() == user.name


def test_safe_name_with_name(user_factory):
    user = user_factory.build()
    assert user.safe_name() == user.name


def test_safe_name_without_name(user_factory):
    user = user_factory.build(name="")
    assert user.safe_name() == user.username


@pytest.mark.django_db()
def test_inidividual_organization(user_factory):
    user = user_factory()
    assert (
        user.individual_organization
        == user.organizations.filter(individual=True).first()
    )


def test_wrap_url(user_factory):
    user = user_factory.build(pk=1)
    url = "http://www.example.com"
    parse = urlsplit(user.wrap_url(url, a=1))
    assert parse.scheme == "http"
    assert parse.netloc == "www.example.com"
    assert parse.path == ""
    query = parse_qs(parse.query)
    assert "url_auth_token" in query
    assert query["a"] == ["1"]


def test_wrap_url_off(user_factory):
    user = user_factory.build(use_autologin=False, pk=1)
    url = "http://www.example.com"
    parse = urlsplit(user.wrap_url(url, a=1))
    assert parse.scheme == "http"
    assert parse.netloc == "www.example.com"
    assert parse.path == ""
    query = parse_qs(parse.query)
    assert "url_auth_token" not in query
    assert query["a"] == ["1"]


@pytest.mark.django_db
def test_can_auto_join(user_factory):
    # Create a user with a verified email address
    user = user_factory()
    user.emailaddress_set.create(email="user@example.com", verified=True)

    # Create organizations using the factory
    # and assign matching domains via EmailDomainFactory
    org1 = OrganizationFactory(name="Org 1", allow_auto_join=True)
    domain1 = EmailDomainFactory.create(organization=org1, domain="example.com")
    org1.domains.set([domain1])

    org2 = OrganizationFactory(name="Org 2")
    domain2 = EmailDomainFactory.create(organization=org2, domain="anotherdomain.com")
    org2.domains.set([domain2])

    # Test that the user can auto-join org1, but not org2
    assert user.can_auto_join(org1) is True
    assert user.can_auto_join(org2) is False


@pytest.mark.django_db
def test_can_auto_join_with_multiple_emails(user_factory):
    # Create a user with multiple verified email addresses
    user = user_factory()
    user.emailaddress_set.create(email="user@example.com", verified=True)
    user.emailaddress_set.create(email="user@anotherdomain.com", verified=True)

    # Create organizations using the factory with domains
    # that match and don't match the user's emails
    org1 = OrganizationFactory(name="Org 1", allow_auto_join=True)
    domain1 = EmailDomainFactory.create(organization=org1, domain="example.com")
    org1.domains.set([domain1])

    org2 = OrganizationFactory(name="Org 2")
    domain2 = EmailDomainFactory.create(organization=org2, domain="anotherdomain.com")
    org2.domains.set([domain2])

    org3 = OrganizationFactory(name="Org 3")
    domain3 = EmailDomainFactory.create(
        organization=org3, domain="nonmatchingdomain.com"
    )
    org3.domains.set([domain3])  # Doesn't match either email

    # Test that the user can auto-join organizations with matching domains
    assert user.can_auto_join(org1) is True

    # Test that the user cannot auto-join org
    # even if they have a matching domain if allow_auto_join is False
    assert user.can_auto_join(org2) is False

    # Test that the user cannot auto-join an organization with a non-matching domain
    assert user.can_auto_join(org3) is False


@pytest.mark.django_db
def test_get_potential_organizations_with_multiple_emails(user_factory):
    # Create a user with multiple verified email addresses
    user = user_factory()
    user.emailaddress_set.create(email="user@example.com", verified=True)
    user.emailaddress_set.create(email="user@anotherdomain.com", verified=True)

    # Create organizations using the factory
    org1 = OrganizationFactory(name="Org 1")
    domain1 = EmailDomainFactory.create(organization=org1, domain="example.com")
    org1.domains.set([domain1])

    org2 = OrganizationFactory(name="Org 2")
    domain2 = EmailDomainFactory.create(organization=org2, domain="anotherdomain.com")
    org2.domains.set([domain2])

    org3 = OrganizationFactory(name="Org 3")
    domain3 = EmailDomainFactory.create(
        organization=org3, domain="nonmatchingdomain.com"
    )
    org3.domains.set([domain3])

    # Test that the user can get the correct potential orgs
    potential_orgs = user.get_potential_organizations()
    assert org1 in potential_orgs
    assert org2 in potential_orgs
    assert org3 not in potential_orgs
