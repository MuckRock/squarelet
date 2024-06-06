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


class ERHLandingView(TemplateView):

    template_name = "core/erh_landing.html"

    def get_context_date(self, **kwargs):
        context = super().get_context_data()
        return context
