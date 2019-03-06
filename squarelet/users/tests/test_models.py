
# Local
from .factories import UserFactory


def test_str():
    username = "testuser"
    user = UserFactory.build(username=username)
    assert str(user) == username


def test_get_absolute_url():
    username = "testuser"
    user = UserFactory.build(username=username)
    assert user.get_absolute_url() == f"/users/{username}/"
