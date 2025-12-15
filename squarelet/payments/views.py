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
import json
import logging
import sys

# Squarelet
from squarelet.organizations.models import Organization, Plan
from squarelet.organizations.models.payment import Subscription
from squarelet.organizations.tasks import add_to_waitlist

logger = logging.getLogger(__name__)


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

        # Add plan data for JSON serialization
        context["plan_data"] = {
            "annual": plan.annual,
        }

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
                    "show_waitlist": not plan.has_available_slots() and plan.wix,
                }
            )

        # Add admin link if user has admin permissions
        if self.request.user.is_authenticated and self.request.user.is_staff:
            context["admin_link"] = reverse(
                "admin:organizations_plan_change", args=[plan.pk]
            )

        return context

    def post(self, request, *args, **kwargs):
        # pylint: disable=too-many-return-statements,too-many-branches
        """
        This receives a form submission for subscribing to the plan.
        The form supports selecting an existing organization or creating a new one,
        and choosing a payment method (new card, existing card, or invoice).

        Except! Invoice handling is getting expanded support in #461—we are only
        using invoices as a silent fallback for when no card has been provided.
        This is an edge case and not a user-selectable option at this time.
        """
        plan = self.get_object()

        if not request.user.is_authenticated:
            # Redirect unauthenticated users to login, then back to this page
            return redirect_to_login(request.get_full_path())

        # pylint: disable=pointless-string-statement
        # It's not pointless, it's a block comment
        """
        # Get form data

        - Organization
            - If creating a new organization, the ID will be "new"
            - If creating a new organization, get the name from the form
        - Stripe token
            - If the user entered a credit card, the stripe_token will be populated
            - If they are using a saved card, this value will be empty.
            - If they are using an existing organization, there's a chance we'll have
              a saved card on file already. If it's a new organization, we should expect
              to have a token value.
        - Payment method: one of "new-card", "existing-card", or "invoice"
            - "new-card": user entered a new card (stripe_token will be populated)
            - "existing-card": user selected an existing saved card (stripe_token empty)
            - "invoice": user selected invoice payment (stripe_token empty)
        """

        organization_id = request.POST.get("organization")
        new_organization_name = request.POST.get("new_organization_name")
        stripe_token = request.POST.get("stripe_token")
        payment_method = request.POST.get("payment_method")
        with transaction.atomic():
            try:
                # Get or create the organization
                if organization_id == "new":
                    # Create a new organization
                    if not new_organization_name:
                        messages.error(
                            request, _("Please provide a name for the new organization")
                        )
                        return redirect(plan)

                    organization = Organization.objects.create(
                        name=new_organization_name,
                        private=False,
                    )
                    # Add the user as an admin
                    organization.add_creator(request.user)
                elif organization_id:
                    organization = Organization.objects.get(
                        pk=organization_id, users=request.user, memberships__admin=True
                    )
                else:
                    organization = request.user.individual_organization

                # Check if already subscribed
                if organization.subscriptions.filter(
                    plan=plan, cancelled=False
                ).exists():
                    # Already subscribed
                    messages.warning(request, _("Already subscribed"))
                    return redirect(plan)

                # Validate payment method matches available options
                if payment_method == "existing-card":
                    if not organization.customer().card:
                        messages.error(
                            request,
                            _("No payment method on file. Please add a card."),
                        )
                        return redirect(plan)
                elif payment_method == "new-card":
                    if not stripe_token:
                        messages.error(request, _("Please provide card information."))
                        return redirect(plan)
                elif payment_method == "invoice":
                    if not plan.annual:
                        messages.error(
                            request,
                            _("Invoice payment is only available for annual plans."),
                        )
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
                            plan=plan,
                            max_users=plan.minimum_users,
                            user=request.user,
                            payment_method=payment_method,
                        )
                    )
                else:
                    # Non-Sunlight plans don't need transaction protection
                    organization.set_subscription(
                        token=stripe_token,
                        plan=plan,
                        max_users=plan.minimum_users,
                        user=request.user,
                        payment_method=payment_method,
                    )

                # Success - redirect to organization page
                messages.success(request, _("Succesfully subscribed"))
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
