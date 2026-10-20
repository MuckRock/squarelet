# Django
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
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
    """Send a stale sign-in form back to where it was going instead of a 403.

    Never processes the POST body. Anything other than a same-origin POST to a
    sign-in view gets Django's default 403.
    """
    match = request.resolver_match
    url_name = match.url_name if match else None
    if url_name not in SIGN_IN_URL_NAMES:
        return csrf.csrf_failure(request, reason=reason)

    origin = request.META.get("HTTP_ORIGIN")
    same_origin = origin == f"{request.scheme}://{request.get_host()}"
    authenticated = request.user.is_authenticated
    logger.warning(
        "Sign-in CSRF failure: reason=%r authenticated=%s url_name=%s origin=%s",
        reason,
        authenticated,
        url_name,
        "absent" if origin is None else ("same" if same_origin else "cross"),
    )
    if origin is not None and not same_origin:
        return csrf.csrf_failure(request, reason=reason)

    if authenticated:
        next_url = request.GET.get("next")
        if not url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            next_url = resolve_url(settings.LOGIN_REDIRECT_URL)
        return redirect(next_url)

    messages.info(request, _("Your sign-in page expired. Please try again."))
    return redirect(request.get_full_path())
