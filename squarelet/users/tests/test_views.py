
# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin

# Local
from .. import views


# pylint: disable=invalid-name


@pytest.mark.django_db()
class TestUserDetailView(ViewTestMixin):
    """Test the User Detail view"""

    view = views.UserDetailView
    url = "/users/{username}/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200
        assert list(response.context_data["other_orgs"]) == list(
            user.organizations.filter(individual=False)
        )
