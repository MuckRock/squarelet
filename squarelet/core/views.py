# Django
from django.urls import reverse
from django.views.generic.base import RedirectView, TemplateView

# Squarelet
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

        # Add Sunlight plans structured by tier and payment schedule
        sunlight_plans_list = Plan.objects.filter(
            slug__startswith="sunlight-", wix=True
        ).order_by("slug")

        # Structure the plans as: tiers -> each tier has monthly and annual plans
        sunlight_tiers = {}
        for plan in sunlight_plans_list:
            # Extract tier from slug: "sunlight-basic", "sunlight-basic-annual"
            if plan.slug.endswith("-annual"):
                tier_name = plan.slug.replace("sunlight-", "").replace("-annual", "")
                payment_type = "annual"
            else:
                tier_name = plan.slug.replace("sunlight-", "")
                payment_type = "monthly"

            if tier_name not in sunlight_tiers:
                sunlight_tiers[tier_name] = {
                    "name": tier_name.title(),
                    "monthly": None,
                    "annual": None,
                }

            sunlight_tiers[tier_name][payment_type] = plan

        # Convert to ordered list for template
        tier_order = ["basic", "premium", "enterprise"]
        context["sunlight_tiers"] = [
            sunlight_tiers[tier] for tier in tier_order if tier in sunlight_tiers
        ]

        return context
