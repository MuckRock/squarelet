# Django
from django.urls import reverse
from django.views.generic.base import RedirectView, TemplateView


class HomeView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return reverse(
                "users:detail", kwargs={"username": self.request.user.username}
            )
        else:
            return reverse("select_plan")


class SelectPlanView(TemplateView):
    template_name = "pages/selectplan.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        pro_plan = None
        org_plans = None
        if not user.is_anonymous:
            pro_plan = user.individual_organization.subscription
            org_plans = user.organizations.filter(
                subscriptions__isnull=False,
                individual=False,
            ).distinct()
        context["user"] = user
        context["pro_plan"] = pro_plan
        context["org_plans"] = org_plans
        return context
