
# Standard Library
from unittest.mock import Mock

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer

# Local
from .. import oidc


def test_userinfo(user_factory):
    user = user_factory.build()
    claims = oidc.userinfo({}, user)
    assert claims["name"] == user.name
    assert claims["preferred_username"] == user.username
    assert claims["updated_at"] == user.updated_at
    assert claims["picture"] == user.avatar_url
    assert claims["email"] == ""
    assert not claims["email_verified"]


def test_scope_uuid(user_factory):
    user = user_factory.build()
    token = Mock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_uuid()
    assert info["uuid"] == user.uuid


def test_scope_organizations(user_factory):
    user = user_factory.build()
    token = Mock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_organizations()
    assert info["organizations"] == [
        MembershipSerializer(m).data
        for m in user.memberships.select_related("organization__plan")
    ]


def test_scope_preferences(user_factory):
    user = user_factory.build()
    token = Mock(user=user)
    claims = oidc.CustomScopeClaims(token)
    info = claims.scope_preferences()
    assert info["use_autologin"] == user.use_autologin
