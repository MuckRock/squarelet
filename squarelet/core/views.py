# Django
from django.db.models import Q
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


class ERHLandingView(TemplateView):

    template_name = "core/erh_landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            context["can_access_hub"] = self.request.user.is_hub_eligible
            context["eligible_orgs"] = self.request.user.organizations.filter(
                Q(individual=False)
                & (
                    Q(hub_eligible=True)
                    | Q(groups__hub_eligible=True)
                    | Q(parent__hub_eligible=True)
                )
            )
            context["group_orgs"] = self.request.user.organizations.filter(
                individual=False
            )
        return context
