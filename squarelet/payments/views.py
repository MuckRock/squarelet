# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, TemplateView

# Standard Library
import logging
import sys

# Squarelet
from squarelet.organizations.models import Organization, Plan
from squarelet.organizations.models.payment import Subscription
from squarelet.organizations.tasks import add_to_waitlist
from squarelet.payments.forms import PlanPurchaseForm

logger = logging.getLogger(__name__)


def get_matching_plan_tier(plan):
    """
    For Sunlight Research Center plans, find the matching plan tier
    with a different payment schedule (monthly <-> annual).
    """
    if not plan.slug.startswith("sunlight-"):
        return None

    if plan.annual:
        # Find monthly equivalent by removing "-annual" suffix
        matching_slug = plan.slug.replace("-annual", "")
    else:
        # Find annual equivalent by adding "-annual" suffix
        matching_slug = f"{plan.slug}-annual"

    try:
        return Plan.objects.get(slug=matching_slug)
    except Plan.DoesNotExist:
        return None


def protect_private_plan(plan, user):
    """Raise 404 if user should not access this private plan"""
    if not plan.public and plan.private_organizations.exists():
        # If user is not authenticated, raise 404
        if not user.is_authenticated:
            raise Http404("Plan not found")

        # If user is not admin of any organization for this plan, raise 404
        user_admin_orgs = user.organizations.filter(memberships__admin=True)
        if not plan.private_organizations.filter(pk__in=user_admin_orgs).exists():
            raise Http404("Plan not found")


class PlanDetailView(DetailView):
    model = Plan
    template_name = "payments/plan.html"

    def get_template_names(self):
        """Override to use custom template for Enterprise plans"""
        plan = self.get_object()

        # Check if this is an Enterprise plan
        if plan.slug.startswith("sunlight-enterprise"):
            return ["payments/plan_enterprise.html"]

        return [self.template_name]

    def get_object(self, queryset=None):
        """Override to check private plan access"""
        if queryset is None:
            queryset = self.get_queryset()

        plan = super().get_object(queryset)

        protect_private_plan(plan, self.request.user)
        return plan

    def get_form(self):
        """Get the plan purchase form"""
        plan = self.get_object()
        user = self.request.user if self.request.user.is_authenticated else None

        if self.request.method == "POST":
            return PlanPurchaseForm(self.request.POST, plan=plan, user=user)
        return PlanPurchaseForm(plan=plan, user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan = self.get_object()

        # Add form to context
        if "form" not in kwargs:
            context["form"] = self.get_form()

        # Add matching plan tier with different payment schedule (for Sunlight plans)
        context["matching_plan"] = get_matching_plan_tier(plan)

        if self.request.user.is_authenticated:
            user = self.request.user
            existing_subscriptions = []

            # Check user's individual organization
            individual_org = user.individual_organization
            individual_subscription = individual_org.subscriptions.filter(
                plan=plan, cancelled=False
            ).first()
            if individual_subscription:
                existing_subscriptions.append((individual_subscription, individual_org))

            # Get organizations where user is admin
            admin_orgs_base = Organization.objects.filter(
                users=user, memberships__admin=True, individual=False
            ).distinct()

            # Filter by private_organizations if populated
            if not plan.public and plan.private_organizations.exists():
                admin_orgs = admin_orgs_base.filter(
                    pk__in=plan.private_organizations.all()
                )
            else:
                admin_orgs = admin_orgs_base

            for org in admin_orgs:
                org_subscription = org.subscriptions.filter(
                    plan=plan, cancelled=False
                ).first()
                if org_subscription:
                    existing_subscriptions.append((org_subscription, org))

            context.update(
                {
                    "existing_subscriptions": existing_subscriptions,
                    "stripe_pk": settings.STRIPE_PUB_KEY,
                    "show_waitlist": not plan.has_available_slots() and plan.wix,
                }
            )

        # Add admin link if user has admin permissions
        if self.request.user.is_authenticated and self.request.user.is_staff:
            context["admin_link"] = reverse(
                "admin:organizations_plan_change", args=[plan.pk]
            )

        # Add nonprofit variant flag for template
        context["is_nonprofit_variant"] = plan.slug.startswith("sunlight-nonprofit-")

        return context

    def _get_org_cards(self, individual_org, admin_orgs):
        """
        Collect saved purchase methods for template context.
        When an org is selected, its saved purchase method should be shown.
        Each org only has 1 saved payment method.
        """
        org_cards = {}

        # Add individual org if it has a card
        if individual_org:
            individual_card = individual_org.customer().card
            if individual_card:
                org_cards[str(individual_org.pk)] = {
                    "last4": individual_card.last4,
                    "brand": individual_card.brand,
                }

        # Add admin organizations that have cards
        for org in admin_orgs:
            org_card = org.customer().card
            if org_card:
                org_cards[str(org.pk)] = {
                    "last4": org_card.last4,
                    "brand": org_card.brand,
                }

        return org_cards

    def post(self, request, *args, **kwargs):
        """
        Handle form submission for subscribing to the plan.
        Uses PlanPurchaseForm for validation and data extraction.
        """
        self.object = self.get_object()
        plan = self.object

        if not request.user.is_authenticated:
            # Redirect unauthenticated users to login, then back to this page
            return redirect_to_login(request.get_full_path())

        form = self.get_form()

        if not form.is_valid():
            # Re-render with form errors
            return self.render_to_response(self.get_context_data(form=form))

        with transaction.atomic():
            try:
                # Get form results
                result = form.save(request.user)
                organization = result["organization"]
                selected_plan = result["plan"]
                payment_method = result["payment_method"]
                stripe_token = result["stripe_token"]

                # Check if already subscribed (check original plan)
                if organization.subscriptions.filter(
                    plan=plan, cancelled=False
                ).exists():
                    messages.warning(request, _("Already subscribed"))
                    return redirect(plan)

                # For Sunlight plans, use transaction with
                # row locking to prevent race conditions
                if plan.slug.startswith("sunlight-") and plan.wix:
                    # Lock subscription records to prevent concurrent subscriptions
                    locked_count = (
                        Subscription.objects.select_for_update().sunlight_active_count()
                    )

                    if locked_count >= settings.MAX_SUNLIGHT_SUBSCRIPTIONS:
                        # Limit reached - add to waitlist
                        transaction.on_commit(
                            lambda: add_to_waitlist.delay(
                                organization.pk, plan.pk, request.user.pk
                            )
                        )
                        messages.success(
                            request,
                            _("You have been added to the waitlist."),
                        )
                        return redirect(plan)

                    # Set subscription inside transaction to prevent race
                    # between getting a correct count and activating the subscription
                    transaction.on_commit(
                        lambda: organization.set_subscription(
                            token=stripe_token,
                            plan=selected_plan,
                            max_users=selected_plan.minimum_users,
                            user=request.user,
                            payment_method=payment_method,
                        )
                    )
                else:
                    # Non-Sunlight plans don't need transaction protection
                    organization.set_subscription(
                        token=stripe_token,
                        plan=selected_plan,
                        max_users=selected_plan.minimum_users,
                        user=request.user,
                        payment_method=payment_method,
                    )

                # Success - redirect to organization page
                messages.success(request, _("Successfully subscribed"))
                return redirect(organization)

            except Organization.DoesNotExist:
                # Invalid organization
                pass
            except Exception as exc:  # pylint: disable=broad-except
                # Handle other errors
                logger.error(
                    "Subscription creation failed: %s", exc, exc_info=sys.exc_info()
                )

        # If we get here, something went wrong - redirect back to plan
        messages.error(request, _("Something went wrong"))
        return redirect(plan)


class SunlightResearchPlansView(TemplateView):
    template_name = "payments/sunlight-research-plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Fetch Sunlight research plans
        sunlight_plans = list(
            Plan.objects.filter(slug__startswith="sunlight-", wix=True)
        )
        context["sunlight_plans"] = sunlight_plans

        # 2. Fetch user subscription information
        # 3. Fetch organization subscription information
        #    for each organization the user administers
        existing_subscriptions = []

        if self.request.user.is_authenticated:
            # Check user's individual organization
            individual_org = self.request.user.individual_organization
            individual_subscriptions = individual_org.subscriptions.filter(
                plan__slug__startswith="sunlight-", plan__wix=True, cancelled=False
            ).select_related("plan")

            for subscription in individual_subscriptions:
                existing_subscriptions.append((subscription.plan, individual_org))

            # Check organizations where user is admin
            admin_orgs = Organization.objects.filter(
                users=self.request.user, memberships__admin=True, individual=False
            ).distinct()

            for org in admin_orgs:
                org_subscriptions = org.subscriptions.filter(
                    plan__slug__startswith="sunlight-", plan__wix=True, cancelled=False
                ).select_related("plan")

                for subscription in org_subscriptions:
                    existing_subscriptions.append((subscription.plan, org))

        context["existing_subscriptions"] = existing_subscriptions

        return context


class PlanRedirectView(RedirectView):
    """
    Redirects ID-only or slug-only plan URLs to the canonical ID+slug format
    """

    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        # Get the plan using ID or slug
        pk = kwargs.get("pk")
        slug = kwargs.get("slug")

        try:
            if pk:
                # ID provided, need to get the slug
                plan = Plan.objects.get(pk=pk)
            elif slug:
                # Slug provided, need to get the ID
                plan = Plan.objects.get(slug=slug)
            else:
                raise Http404("Invalid plan URL")

            protect_private_plan(plan, self.request.user)

            return reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})

        except Plan.DoesNotExist:
            raise Http404("No Plan found matching the query")
