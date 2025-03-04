# Standard Library
from unittest.mock import MagicMock

# Third Party
import pytest

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer

# Local
from .. import oidc


@pytest.mark.django_db()
def test_userinfo(user_factory):
    user = user_factory()
    claims = oidc.userinfo({}, user)
    assert claims["name"] == user.name
    assert claims["preferred_username"] == user.username
    assert claims["updated_at"] == user.updated_at
    assert claims["picture"] == user.avatar_url
    assert claims["email"] == user.email
    assert not claims["email_verified"]


@pytest.mark.django_db()
def test_scope_uuid(user_factory):
    user = user_factory()
    token = MagicMock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_uuid()
    assert info["uuid"] == user.uuid


@pytest.mark.django_db()
def test_scope_organizations(user_factory, mocker):
    mocker.patch(
        "squarelet.organizations.models.Customer.stripe_customer",
        default_source=None,
    )
    user = user_factory()
    token = MagicMock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_organizations()
    assert info["organizations"] == [
        MembershipSerializer(m).data for m in user.memberships.all()
    ]


@pytest.mark.django_db()
def test_scope_preferences(user_factory):
    user = user_factory()
    token = MagicMock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_preferences()
    assert info["use_autologin"] == user.use_autologin
