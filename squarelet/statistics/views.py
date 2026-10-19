# Django
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView

# Squarelet
from squarelet.statistics.kpis import cached_monthly_activity


class KPIDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Staff dashboard of monthly active and multi-service users"""

    template_name = "statistics/kpis.html"

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activity"] = cached_monthly_activity()
        return context
