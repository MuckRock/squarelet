# Django
from django.core.exceptions import PermissionDenied
from django.test import Client

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.statistics import views


@pytest.mark.django_db()
class TestUserDashboardView(ViewTestMixin):
    view = views.UserDashboardView
    url = "/statistics/users/"

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

    def test_the_old_kpis_address_redirects_here(self):
        response = Client().get("/statistics/kpis/")

        assert response.status_code == 301
        assert response.url == self.url


@pytest.mark.django_db()
class TestRevenueDashboardView(ViewTestMixin):
    view = views.RevenueDashboardView
    url = "/statistics/revenue/"

    def test_anonymous_users_are_sent_to_log_in(self, rf):
        response = self.call_view(rf)

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_non_staff_users_are_refused(self, rf, user_factory):
        with pytest.raises(PermissionDenied):
            self.call_view(rf, user_factory())

    def test_staff_see_the_cached_report(self, rf, user_factory, mocker):
        report = {"generated_at": "2026-10-21T05:45:00-04:00", "months": []}
        mocker.patch(
            "squarelet.statistics.views.cached_revenue_report", return_value=report
        )
        refresh = mocker.patch("squarelet.statistics.views.refresh_revenue_report")

        response = self.call_view(rf, user_factory(is_staff=True))

        assert response.context_data["report"] == report
        refresh.delay.assert_not_called()

    def test_an_empty_cache_queues_a_refresh(self, rf, user_factory, mocker):
        mocker.patch(
            "squarelet.statistics.views.cached_revenue_report", return_value=None
        )
        refresh = mocker.patch("squarelet.statistics.views.refresh_revenue_report")

        response = self.call_view(rf, user_factory(is_staff=True))
        response.render()

        refresh.delay.assert_called_once_with()
        assert b"being prepared" in response.content


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "url, current",
    [("/statistics/users/", "Users"), ("/statistics/revenue/", "Revenue")],
)
def test_each_dashboard_marks_its_own_tab(url, current, user_factory, mocker):
    mocker.patch("squarelet.statistics.views.refresh_revenue_report")
    client = Client()
    client.force_login(user_factory(is_staff=True))

    content = client.get(url).content.decode()

    assert f'aria-current="page">{current}</a>' in content
    assert content.count('aria-current="page"') == 1
