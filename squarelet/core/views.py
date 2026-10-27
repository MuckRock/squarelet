# Django
from django.shortcuts import render
from django.urls import reverse
from django.views import csrf
from django.views.generic.base import RedirectView, TemplateView

# Standard Library
import logging

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.organizations.models import Plan

logger = logging.getLogger(__name__)

# The forms a user submits to sign in; a stale token on one of these is
# almost always an old tab or a double submit, not an attack.
SIGN_IN_URL_NAMES = {"account_login", "account_signup", "mfa_authenticate"}


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
        # pylint: disable=too-many-locals
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

        # Add Sunlight plans structured by tier and payment schedule
        sunlight_plans_list = Plan.objects.filter(
            slug__startswith="sunlight-", wix=True
        ).order_by("slug")

        # Structure the plans as: tiers -> each tier has monthly and annual plans
        sunlight_tiers = {}
        for plan in sunlight_plans_list:
            # Extract tier from slug: "sunlight-essential", "sunlight-essential-annual"
            if plan.slug.endswith("-annual"):
                tier_name = plan.slug.replace("sunlight-", "").replace("-annual", "")
                payment_type = "annual"
            else:
                tier_name = plan.slug.replace("sunlight-", "")
                payment_type = "monthly"

            if tier_name not in sunlight_tiers:
                sunlight_tiers[tier_name] = {
                    "name": tier_name.title(),
                    "short_description": plan.short_description,
                    "monthly": None,
                    "annual": None,
                }

            sunlight_tiers[tier_name][payment_type] = plan

        # Fetch nonprofit variant plans and add them to tiers
        for tier_name, tier_data in sunlight_tiers.items():
            for payment_type in ["monthly", "annual"]:
                if tier_data[payment_type]:
                    standard_plan = tier_data[payment_type]
                    nonprofit_slug = standard_plan.nonprofit_variant_slug
                    if nonprofit_slug:
                        try:
                            nonprofit_plan = Plan.objects.get(slug=nonprofit_slug)
                            tier_data[payment_type] = {
                                "standard": standard_plan,
                                "nonprofit": nonprofit_plan,
                            }
                        except Plan.DoesNotExist:
                            # No nonprofit variant exists, keep the standard plan
                            tier_data[payment_type] = {
                                "standard": standard_plan,
                                "nonprofit": None,
                            }

        # Convert to ordered list for template
        tier_order = ["essential", "enhanced", "enterprise"]
        context["sunlight_tiers"] = [
            sunlight_tiers[tier] for tier in tier_order if tier in sunlight_tiers
        ]
        if not user.is_anonymous:
            for tier in context["sunlight_tiers"]:
                prices = tier["annual"] or tier["monthly"]
                plan = prices["standard"] if isinstance(prices, dict) else prices
                tier["checkout_url"] = plan and plan.get_checkout_url_for(user)

        return context


def page_not_found(request, exception, template_name="404.html"):
    context = {}
    if exception and exception.args and isinstance(exception.args[0], str):
        context["message"] = exception.args[0]
    # structured context from ContextHttp404
    if isinstance(exception, ContextHttp404):
        context.update(exception.context)
    return render(request, template_name, context, status=404)


def csrf_failure(request, reason=""):
    """Log a CSRF failure on a sign-in form, then return Django's default 403."""
    match = request.resolver_match
    url_name = match.url_name if match else None
    if url_name in SIGN_IN_URL_NAMES:
        origin = request.META.get("HTTP_ORIGIN")
        same_origin = origin == f"{request.scheme}://{request.get_host()}"
        request_id = request.META.get("HTTP_X_REQUEST_ID", "none")
        logger.warning(
            "Sign-in CSRF failure: reason=%r authenticated=%s url_name=%s "
            "origin=%s request_id=%s",
            reason,
            request.user.is_authenticated,
            url_name,
            "absent" if origin is None else ("same" if same_origin else "cross"),
            request_id,
        )
    return csrf.csrf_failure(request, reason=reason)
