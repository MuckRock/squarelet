# Django
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import DetailView, RedirectView, TemplateView

# Standard Library
import json

# Squarelet
from squarelet.organizations.models import Plan, Organization


class PlanDetailView(DetailView):
    model = Plan
    template_name = "payments/plan.html"

    def get_context_data(self, **kwargs):
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
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())

        # Get form data
        organization_id = request.POST.get("organization")
        stripe_token = request.POST.get("stripe_token")
        payment_method = request.POST.get("payment_method", "new")
        save_card = request.POST.get("save_card") == "on"

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
                return redirect(plan)

            # Handle payment method
            customer = organization.customer()

            if payment_method == "new" and stripe_token:
                # Save new card if requested
                if save_card:
                    customer.save_card(stripe_token)
                else:
                    customer.add_source(stripe_token)
            elif payment_method == "existing" and not customer.card:
                # Fallback if existing card not found
                if stripe_token:
                    customer.save_card(stripe_token)

            # Create and start subscription
            subscription = organization.subscriptions.create(plan=plan)
            subscription.start()
            subscription.save()

            # Success - redirect to plan page or success page
            return redirect(plan)

        except Organization.DoesNotExist:
            # Invalid organization
            pass
        except Exception as e:
            # Handle other errors
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Subscription creation failed: {str(e)}")

        # If we get here, something went wrong - redirect back to plan
        return redirect(plan)


class SunlightResearchPlansView(TemplateView):
    template_name = "payments/sunlight-research-plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Fetch Sunlight research plans
        sunlight_plans = list(Plan.objects.filter(slug__startswith="src-", wix=True))
        context["sunlight_plans"] = sunlight_plans

        # 2. Fetch user subscription information
        # 3. Fetch organization subscription information
        #    for each organization the user administers
        existing_subscriptions = []

        if self.request.user.is_authenticated:
            # Check user's individual organization
            individual_org = self.request.user.individual_organization
            individual_subscriptions = individual_org.subscriptions.filter(
                plan__slug__startswith="src-", plan__wix=True, cancelled=False
            ).select_related("plan")

            for subscription in individual_subscriptions:
                existing_subscriptions.append((subscription.plan, individual_org))

            # Check organizations where user is admin
            admin_orgs = Organization.objects.filter(
                users=self.request.user, memberships__admin=True, individual=False
            ).distinct()

            for org in admin_orgs:
                org_subscriptions = org.subscriptions.filter(
                    plan__slug__startswith="src-", plan__wix=True, cancelled=False
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
                return reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
            elif slug:
                # Slug provided, need to get the ID
                plan = Plan.objects.get(slug=slug)
                return reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
        except Plan.DoesNotExist:
            raise Http404("No Plan found matching the query")

        # Should not reach here
        raise Http404("Invalid plan URL")
