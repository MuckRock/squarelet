# Django
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView

# Squarelet
from squarelet.statistics.kpis import cached_monthly_activity
from squarelet.statistics.revenue import cached_revenue_report
from squarelet.statistics.tasks import refresh_revenue_report


class StaffDashboardMixin(LoginRequiredMixin, UserPassesTestMixin):
    """A staff-only statistics dashboard; `dashboard` names its nav tab."""

    dashboard = None

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dashboard"] = self.dashboard
        return context


class UserDashboardView(StaffDashboardMixin, TemplateView):
    """Staff dashboard of monthly active and multi-service users"""

    template_name = "statistics/users.html"
    dashboard = "users"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activity"] = cached_monthly_activity()
        return context


class RevenueDashboardView(StaffDashboardMixin, TemplateView):
    """Staff dashboard of subscription growth and churn from Stripe"""

    template_name = "statistics/revenue.html"
    dashboard = "revenue"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["report"] = cached_revenue_report()
        if context["report"] is None:
            # Building it pages all of Stripe, which outlasts the request timeout.
            refresh_revenue_report.delay()
        return context
