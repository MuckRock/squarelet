# Django
from django.views.generic.base import TemplateView

class SunlightResearchPlansView(TemplateView):
    template_name = "payments/sunlight-research-plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 1. Fetch Sunlight research plans
        # 2. Fetch user subscription information
        # 3. Fetch organization subscription information
        #    for each organization the user administers

        return context