# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
    View,
)

# Standard Library
import logging
import sys
from datetime import datetime

# Third Party
import stripe

# Squarelet
from squarelet.core.utils import format_stripe_error
from squarelet.organizations.models import Charge, Organization, Plan
from squarelet.organizations.models.payment import Subscription, get_payment_brand
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.exceptions import SubscriptionError
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.tasks import add_to_waitlist
from squarelet.payments.forms import (
    CancelSubscriptionForm,
    CardForm,
    PlanPurchaseForm,
    UpdateReceiptEmailForm,
    UpdateSubscriptionFrequencyForm,
)

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
        purchase_redirect = self.request.GET.get("purchase_redirect", "")

        if self.request.method == "POST":
            return PlanPurchaseForm(self.request.POST, plan=plan, user=user)
        return PlanPurchaseForm(
            plan=plan,
            user=user,
            initial={"purchase_redirect": purchase_redirect},
        )

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
                plan=plan
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
                org_subscription = org.subscriptions.filter(plan=plan).first()
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

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _get_org_cards(self, individual_org, admin_orgs):
        """
        Collect saved purchase methods for template context.
        When an org is selected, its saved purchase method should be shown.
        Each org only has 1 saved payment method.
        """
        org_cards = {}

        # Add individual org if it has a payment method on file
        if individual_org:
            individual_card = individual_org.customer().payment_details
            if individual_card:
                org_cards[str(individual_org.pk)] = {
                    "last4": individual_card.last4,
                    "brand": get_payment_brand(individual_card),
                }

        # Add admin organizations that have a payment method on file
        for org in admin_orgs:
            org_card = org.customer().payment_details
            if org_card:
                org_cards[str(org.pk)] = {
                    "last4": org_card.last4,
                    "brand": get_payment_brand(org_card),
                }

        return org_cards

    def post(
        self, request, *args, **kwargs
    ):  # pylint: disable=too-many-return-statements
        """Handle form submission for subscribing to the plan."""
        self.object = self.get_object()
        plan = self.object

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        form = self.get_form()
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        with transaction.atomic():
            try:
                result = form.save(request.user)
                organization = result["organization"]

                if organization.subscriptions.filter(plan=plan).exists():
                    messages.warning(request, _("Already subscribed"))
                    return redirect(plan)

                early_response = self._subscribe(request, plan, result)
                if early_response is not None:
                    return early_response

                messages.success(request, _("Successfully subscribed"))
                purchase_redirect = form.cleaned_data.get("purchase_redirect", "")
                redirect_url = purchase_redirect or organization.get_absolute_url()
                if self._is_ajax():
                    return JsonResponse(
                        {
                            "redirect": redirect_url,
                            "message": str(_("Successfully subscribed")),
                        }
                    )
                return redirect(purchase_redirect or organization)

            except Organization.DoesNotExist:
                pass
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Subscription creation failed: %s", exc, exc_info=sys.exc_info()
                )

        if self._is_ajax():
            return JsonResponse({"error": str(_("Something went wrong"))}, status=400)
        messages.error(request, _("Something went wrong"))
        return redirect(plan)

    def _subscribe(self, request, plan, result):
        """
        Dispatch to the Sunlight or regular subscription path.

        Returns an HttpResponse for early exits (waitlist, 3DS, Stripe errors),
        or None to signal the caller should build the success response.
        """
        if plan.slug.startswith("sunlight-") and plan.wix:
            return self._handle_sunlight_subscription(request, plan, result)
        return self._handle_regular_subscription(request, plan, result)

    def _handle_sunlight_subscription(self, request, plan, result):
        """Rate-limit with row locking; add to waitlist or defer subscription."""
        organization = result["organization"]
        selected_plan = result["plan"]
        stripe_token = result["stripe_token"]
        payment_method = result["payment_method"]

        locked_count = Subscription.objects.select_for_update().sunlight_active_count()
        if locked_count >= settings.MAX_SUNLIGHT_SUBSCRIPTIONS:
            transaction.on_commit(
                lambda: add_to_waitlist.delay(organization.pk, plan.pk, request.user.pk)
            )
            messages.success(request, _("You have been added to the waitlist."))
            return redirect(plan)
        transaction.on_commit(
            lambda: organization.add_subscription(
                selected_plan,
                selected_plan.minimum_users,
                request.user,
                token=stripe_token,
                payment_method=payment_method,
            )
        )
        return None

    def _handle_regular_subscription(self, request, plan, result):
        """Call add_subscription directly; return error response or None on success."""
        # pylint: disable=too-many-return-statements
        organization = result["organization"]
        selected_plan = result["plan"]
        stripe_token = result["stripe_token"]
        payment_method = result["payment_method"]

        try:
            organization.add_subscription(
                selected_plan,
                selected_plan.minimum_users,
                request.user,
                token=stripe_token,
                payment_method=payment_method,
            )
            return None
        except PaymentActionRequired as exc:
            # Subscription saved but first invoice needs 3DS.
            redirect_url = organization.get_absolute_url()
            if self._is_ajax():
                return JsonResponse(
                    {
                        "client_secret": exc.client_secret,
                        "payment_intent_id": exc.payment_intent_id,
                        "redirect": redirect_url,
                    },
                    status=402,
                )
            messages.error(
                request,
                _("Your card requires additional authentication. Please try again."),
            )
            return redirect(plan)
        except SubscriptionError as exc:
            logger.error("Duplicate subscription attempt: %s", exc)
            if self._is_ajax():
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect(plan)
        except stripe.StripeError as exc:
            logger.error(
                "Stripe error during subscription: %s",
                exc,
                exc_info=sys.exc_info(),
            )
            if self._is_ajax():
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(request, str(exc))
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
                plan__slug__startswith="sunlight-", plan__wix=True
            ).select_related("plan")

            for subscription in individual_subscriptions:
                existing_subscriptions.append((subscription.plan, individual_org))

            # Check organizations where user is admin
            admin_orgs = Organization.objects.filter(
                users=self.request.user, memberships__admin=True, individual=False
            ).distinct()

            for org in admin_orgs:
                org_subscriptions = org.subscriptions.filter(
                    plan__slug__startswith="sunlight-", plan__wix=True
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

            url = reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
            if self.request.META.get("QUERY_STRING"):
                url = f"{url}?{self.request.META['QUERY_STRING']}"
            return url

        except Plan.DoesNotExist:
            raise Http404("No Plan found matching the query")


class PaymentsHubView(LoginRequiredMixin, TemplateView):
    """Cross-organization payments hub.

    Shows the most recent payments for every account whose charges the user
    can view — their personal account and any organization they administer
    (``can_view_charge`` is admin-only). Each account links out to its full
    payment history so the user can dig deeper.
    """

    template_name = "payments/payments_hub.html"
    recent_limit = 5

    def _subject_url(self, organization, name):
        """Reverse a subject-scoped URL for the account.

        Organization pages are keyed on the org slug; the personal account's
        pages live under the ``users`` namespace and are keyed on the
        member's username.
        """
        if organization.individual:
            return reverse(
                f"users:{name}", kwargs={"username": self.request.user.username}
            )
        return reverse(f"organizations:{name}", kwargs={"slug": organization.slug})

    def get_accounts(self):
        """Build per-account context: the organization, its most recent
        charges, the card on file, and the URLs used to manage it."""
        user = self.request.user
        organizations = [user.individual_organization]
        organizations += list(
            user.organizations.filter(individual=False, memberships__admin=True)
            .distinct()
            .order_by("name")
        )

        accounts = []
        for organization in organizations:
            customer = organization.customer()
            accounts.append(
                {
                    "organization": organization,
                    "payments": list(
                        organization.charges.order_by("-created_at")[
                            : self.recent_limit
                        ]
                    ),
                    "card_brand": customer.payment_brand,
                    "card_last4": customer.payment_last4,
                    "history_url": self._subject_url(organization, "payments"),
                    "manage_url": self._subject_url(organization, "subscriptions"),
                    "update_card_url": self._subject_url(organization, "update-card"),
                }
            )
        return accounts

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["accounts"] = self.get_accounts()
        return context


class SubscriptionObjectMixin:
    """Resolve the organization for a subscription view and build the
    subject-scoped URLs used to move between its pages.

    Organization views key these URLs on the organization slug. User
    views key them on the member's username — the individual organization
    is an implementation detail that is never exposed in the URL — by
    setting ``subject_url_kwarg = "username"`` and overriding
    ``get_organization``.
    """

    subject = None
    subject_url_kwarg = "slug"
    individual = False

    def get_organization(self):
        return get_object_or_404(
            Organization,
            individual=self.individual,
            slug=self.kwargs[self.subject_url_kwarg],
        )

    def get_object(self, queryset=None):
        # pylint: disable=unused-argument
        return self.get_organization()

    def get_subject_url_kwargs(self):
        return {self.subject_url_kwarg: self.kwargs[self.subject_url_kwarg]}

    def reverse_subject(self, name, **kwargs):
        """Reverse a subject-scoped URL (e.g. ``users:subscriptions``)."""
        return reverse(
            f"{self.subject}:{name}",
            kwargs={**self.get_subject_url_kwargs(), **kwargs},
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = self.subject
        context["subject_slug"] = self.kwargs[self.subject_url_kwarg]
        return context


class BaseManageSubscriptions(SubscriptionObjectMixin, DetailView):
    template_name = "subscriptions/manage_subscriptions.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get subscriptions and add renewal/cancellation date and cost data
        subscriptions = self.object.subscriptions.all()
        for subscription in subscriptions:
            subscription.next_date = get_subscription_next_date(subscription)
            subscription.cost = subscription.plan.base_price
        context["subscriptions"] = subscriptions

        # Get card on file
        customer = self.object.customer()
        context["card_brand"] = customer.payment_brand
        context["card_last4"] = customer.payment_last4

        # Get all receipt emails
        context["receipt_emails"] = self.object.receipt_emails.all()

        # Get failed receipt emails
        context["failed_receipt_emails"] = self.object.receipt_emails.filter(
            failed=True
        )

        # Get five most recent payments
        payments = self.object.charges.order_by("-created_at").all()[:5]
        context["payments"] = payments

        return context


class BaseUpdateSubscriptionFrequency(SubscriptionObjectMixin, UpdateView):
    form_class = UpdateSubscriptionFrequencyForm
    template_name = "subscriptions/update_subscription_frequency.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscription = self.object.subscriptions.filter(id=self.kwargs["pk"]).first()
        context["subscription"] = subscription
        context["next_date"] = get_subscription_next_date(subscription)

        return context


class BaseUpdateCard(SubscriptionObjectMixin, UpdateView):
    """Update the credit card on file for an organization."""

    form_class = CardForm
    template_name = "subscriptions/update_card.html"

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def form_valid(self, form):
        organization = self.object
        user = self.request.user
        redirect_url = self.reverse_subject("subscriptions")
        token = form.cleaned_data["stripe_token"]
        try:
            organization.save_card(token, user)
        except stripe.StripeError as exc:
            user_message = format_stripe_error(exc)
            if self._is_ajax():
                return JsonResponse({"error": user_message}, status=400)
            messages.error(self.request, f"Payment error: {user_message}")
            return redirect(redirect_url)
        else:
            success_msg = _("Credit card updated")
            if self._is_ajax():
                return JsonResponse(
                    {"redirect": redirect_url, "message": str(success_msg)}
                )
            messages.success(self.request, success_msg)
        return redirect(redirect_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.object.customer()
        context["card_brand"] = customer.payment_brand
        context["card_last4"] = customer.payment_last4

        return context


class BaseRemoveCard(SubscriptionObjectMixin, View):
    """Remove the credit card on file for an organization."""

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _error(self, message):
        """Return the error as JSON for AJAX callers, else flash and redirect."""
        if self._is_ajax():
            return JsonResponse({"error": str(message)}, status=400)
        messages.error(self.request, message)
        return redirect(self.reverse_subject("subscriptions"))

    def post(self, request, *args, **kwargs):
        organization = self.get_object()
        redirect_url = self.reverse_subject("subscriptions")

        if organization.customer().payment_details is None:
            return self._error(_("You do not have a card on file to remove."))

        # A non-cancelled subscription still bills the card on file, so removing
        # it would set up a failed renewal. Require cancellation first.
        if organization.subscriptions.filter(cancelled=False).exists():
            return self._error(
                _(
                    "You must cancel your active subscriptions before "
                    "removing your payment method."
                )
            )

        try:
            organization.remove_payment_method()
        except stripe.StripeError as exc:
            return self._error(f"Payment error: {format_stripe_error(exc)}")

        success_msg = _("Credit card removed")
        if self._is_ajax():
            return JsonResponse({"redirect": redirect_url, "message": str(success_msg)})
        messages.success(request, success_msg)
        return redirect(redirect_url)


class BaseUpdateReceiptEmail(SubscriptionObjectMixin, UpdateView):
    form_class = UpdateReceiptEmailForm
    template_name = "subscriptions/update_receipt_email.html"

    def form_valid(self, form):
        self.object.set_receipt_emails(form.cleaned_data["receipt_emails"])
        return redirect(self.reverse_subject("subscriptions"))

    def get_initial(self):
        return {
            "receipt_emails": ", ".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class BaseCancelSubscription(SubscriptionObjectMixin, UpdateView):
    form_class = CancelSubscriptionForm
    template_name = "subscriptions/cancel_subscription.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subscription = self.object.subscriptions.filter(id=self.kwargs["pk"]).first()
        if subscription:
            context["subscription"] = subscription
            context["next_date"] = get_subscription_next_date(subscription)
        return context

    def form_valid(self, form):
        organization = self.object
        subscription = self.object.subscriptions.filter(id=self.kwargs["pk"]).first()
        if subscription:
            organization.remove_subscription(subscription)
        messages.success(self.request, _("Subscription cancelled."))
        return redirect(self.reverse_subject("subscriptions"))


class BasePaymentsList(SubscriptionObjectMixin, ListView):
    template_name = "subscriptions/payments.html"
    paginate_by = 20

    def get_queryset(self):
        return Charge.objects.filter(organization=self.get_organization())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.get_organization()
        return context


def get_subscription_next_date(subscription):
    stripe_sub = subscription.stripe_subscription
    if stripe_sub:
        time_stamp = (
            get_payment_provider()
            .get_subscription_service()
            .get_current_period_end(stripe_sub)
        )
        if time_stamp:
            tz_datetime = datetime.fromtimestamp(
                time_stamp, tz=timezone.get_current_timezone()
            )
            return tz_datetime.date()
    return None
