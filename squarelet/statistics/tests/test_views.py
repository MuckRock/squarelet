# Django
from django.core.exceptions import PermissionDenied

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.statistics import views


@pytest.mark.django_db()
class TestKPIDashboardView(ViewTestMixin):
    view = views.KPIDashboardView
    url = "/statistics/kpis/"

    def test_anonymous_users_are_sent_to_log_in(self, rf):
        response = self.call_view(rf)

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_non_staff_users_are_refused(self, rf, user_factory):
        with pytest.raises(PermissionDenied):
            self.call_view(rf, user_factory())

    def test_staff_see_monthly_activity(self, rf, user_factory):
        response = self.call_view(rf, user_factory(is_staff=True))

        assert response.status_code == 200
        assert len(response.context_data["activity"]["months"]) == 24
