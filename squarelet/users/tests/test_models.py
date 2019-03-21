# Standard Library
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

# Third Party
import pytest


def test_str(user_factory):
    user = user_factory.build()
    assert str(user) == user.username


@pytest.mark.django_db(transaction=True)
def test_save(user_factory, mocker):
    mocked = mocker.patch("squarelet.users.models.send_cache_invalidations")
    user = user_factory()
    mocked.assert_called_with("user", user.uuid)


def test_get_absolute_urluser(user_factory):
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
