# Django
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView

# Squarelet
from squarelet.statistics.kpis import cached_monthly_activity


class StaffDashboardMixin(LoginRequiredMixin, UserPassesTestMixin):
    """A statistics dashboard only staff can see."""

    def test_func(self):
        return self.request.user.is_staff


class UserDashboardView(StaffDashboardMixin, TemplateView):
    """Staff dashboard of monthly active and multi-service users"""

    template_name = "statistics/users.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activity"] = cached_monthly_activity()
        return context
