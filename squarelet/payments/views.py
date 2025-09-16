# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, TemplateView

# Standard Library
import json
import logging
import sys

# Squarelet
from squarelet.organizations.models import Organization, Plan

logger = logging.getLogger(__name__)


def protect_private_plan(plan, user):
    """Raise 404 if user should not access this private plan"""
    if plan.private_organizations.exists():
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

    def get_object(self, queryset=None):
        """Override to check private plan access"""
        if queryset is None:
            queryset = self.get_queryset()

        plan = super().get_object(queryset)

        protect_private_plan(plan, self.request.user)
        return plan

    def get_context_data(self, **kwargs):
        # pylint: disable=too-many-locals
        context = super().get_context_data(**kwargs)
        plan = self.get_object()

        if self.request.user.is_authenticated:
            user = self.request.user
            existing_subscriptions = []
            admin_organizations = []

            # Check user's individual organization
            individual_org = user.individual_organization
            individual_subscription = individual_org.subscriptions.filter(
                plan=plan, cancelled=False
            ).first()
            if individual_subscription:
                existing_subscriptions.append((individual_subscription, individual_org))

            # Get organizations where user is admin
            admin_orgs = Organization.objects.filter(
                users=user, memberships__admin=True, individual=False
            ).distinct()

            for org in admin_orgs:
                org_subscription = org.subscriptions.filter(
                    plan=plan, cancelled=False
                ).first()
                if org_subscription:
                    existing_subscriptions.append((org_subscription, org))
                else:
                    admin_organizations.append(org)

            # Check if individual org can subscribe (not already subscribed)
            can_subscribe_individual = not individual_subscription

            # Add default payment methods for organizations
            individual_card = individual_org.customer().card
            if individual_card:
                context["individual_default_card"] = individual_card

            # Build org_cards mapping for all organizations (individual + admin)
            org_cards = {}

            # Add individual org if it has a card
            if individual_card:
                org_cards[str(individual_org.pk)] = {
                    "last4": individual_card.last4,
                    "brand": individual_card.brand,
                }

            # Add admin organizations that have cards
            for org in admin_organizations:
                org_card = org.customer().card
                if org_card:
                    org_cards[str(org.pk)] = {
                        "last4": org_card.last4,
                        "brand": org_card.brand,
                    }

            context.update(
                {
                    "existing_subscriptions": existing_subscriptions,
                    "admin_organizations": admin_organizations,
                    "can_subscribe_individual": can_subscribe_individual,
                    "individual_organization": individual_org,
                    "org_cards": org_cards,
                    "org_cards_json": json.dumps(org_cards),
                    "stripe_pk": settings.STRIPE_PUB_KEY,
                }
            )

        # Add admin link if user has admin permissions
        if self.request.user.is_authenticated and self.request.user.is_staff:
            context["admin_link"] = reverse(
                "admin:organizations_plan_change", args=[plan.pk]
            )

        return context

    def post(self, request, *args, **kwargs):
        plan = self.get_object()

        if not request.user.is_authenticated:
            # Redirect unauthenticated users to login, then back to this plan

            return redirect_to_login(request.get_full_path())

        # Get form data
        organization_id = request.POST.get("organization")
        stripe_token = request.POST.get("stripe_token")

        try:
            # Get the organization
            if organization_id:
                organization = Organization.objects.get(
                    pk=organization_id, users=request.user, memberships__admin=True
                )
            else:
                organization = request.user.individual_organization

            # Check if already subscribed
            if organization.subscriptions.filter(plan=plan, cancelled=False).exists():
                # Already subscribed
                messages.warning(request, _("Already subscribed"))
                return redirect(plan)

            # Handle payment method
            organization.set_subscription(
                token=stripe_token,
                plan=plan,
                max_users=plan.minimum_users,
                user=request.user,
            )

            # Success - redirect to plan page or success page
            messages.success(request, _("Succesfully subscribed"))
            return redirect(plan)

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
