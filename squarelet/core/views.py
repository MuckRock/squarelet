# Django
from django.shortcuts import render
from django.urls import reverse
from django.views.generic.base import RedirectView, TemplateView

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.organizations.models import Plan


class HomeView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return reverse(
                "users:detail", kwargs={"username": self.request.user.username}
            )
        else:
            return reverse("select_plan")


def sunlight_tiers():
    """The Sunlight tiers and their prices, for the plan page.

    One entry per canonical Sunlight plan, in tier order, each carrying
    the plan and its list prices by interval and label::

        {"name": "Essential", "plan": <Plan>, "short_description": ...,
         "monthly": {"standard": <PlanPrice>, "nonprofit": <PlanPrice>},
         "annual": {...}}

    A missing price is None.  Read off `PlanPrice` rather than off the
    separate `*-annual` and `sunlight-nonprofit-*` rows those used to be,
    so the numbers shown are the ones a purchase is sold at.
    """
    tier_order = ["sunlight-essential", "sunlight-enhanced", "sunlight-enterprise"]
    plans = {
        plan.slug: plan
        for plan in Plan.objects.filter(product="sunlight", wix=True).prefetch_related(
            "prices", "entitlements"
        )
    }
    tiers = []
    for slug in tier_order:
        plan = plans.get(slug)
        if plan is None:
            continue
        tier = {
            "name": plan.slug.replace("sunlight-", "").title(),
            "plan": plan,
            "short_description": plan.short_description,
            "monthly": {"standard": None, "nonprofit": None},
            "annual": {"standard": None, "nonprofit": None},
        }
        for price in plan.prices.all():
            if (
                price.active
                and not price.code
                and price.label in ("standard", "nonprofit")
            ):
                tier[price.interval][price.label] = price
        tiers.append(tier)
    return tiers


class SelectPlanView(TemplateView):
    template_name = "pages/selectplan.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        pro_plan = None
        org_plans = None
        if not user.is_anonymous:
            pro_plan = user.individual_organization.subscription_items.first()
            org_plans = user.organizations.filter(
                subscriptions__items__isnull=False,
                individual=False,
            ).distinct()
        context["user"] = user
        context["pro_plan"] = pro_plan
        context["org_plans"] = org_plans

        context["sunlight_tiers"] = sunlight_tiers()
        return context


def page_not_found(request, exception, template_name="404.html"):
    context = {}
    if exception and exception.args and isinstance(exception.args[0], str):
        context["message"] = exception.args[0]
    # structured context from ContextHttp404
    if isinstance(exception, ContextHttp404):
        context.update(exception.context)
    return render(request, template_name, context, status=404)
