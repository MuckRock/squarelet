# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, TimestampSigner
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import urlencode
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
import time

# Third Party
import stripe

# Squarelet
from squarelet.core.utils import format_stripe_error, new_action
from squarelet.organizations.models import Charge, Organization, Plan, PlanPrice
from squarelet.organizations.models.payment import (
    ReceiptEmail,
    SubscriptionItem,
    get_payment_brand,
)
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.exceptions import SubscriptionError
from squarelet.organizations.plan_mapping import tier_of
from squarelet.organizations.tasks import add_to_waitlist
from squarelet.payments.forms import (
    CancelSubscriptionForm,
    CardForm,
    PlanPurchaseForm,
    UpdateReceiptEmailForm,
)

# pylint: disable=too-many-lines

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
            individual_subscription = individual_org.line_holding(plan)
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
                org_subscription = org.line_holding(plan)
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

                held = organization.line_holding(result["plan"])
                if held is not None and held.subscription.kind != "free":
                    messages.warning(request, _("Already subscribed"))
                    return redirect(request.path)

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
        return redirect(request.path)

    def _subscribe(self, request, plan, result):
        """
        Dispatch to the Sunlight or regular subscription path.

        Returns an HttpResponse for early exits (waitlist, 3DS, Stripe errors),
        or None to signal the caller should build the success response.
        """
        if plan.slug.startswith("sunlight-") and plan.wix:
            return self._handle_sunlight_subscription(request, plan, result)
        return self._handle_regular_subscription(request, result)

    def _handle_sunlight_subscription(self, request, plan, result):
        """Rate-limit with row locking; add to waitlist or defer subscription."""
        organization = result["organization"]
        selected_plan = result["plan"]
        stripe_token = result["stripe_token"]
        payment_method = result["payment_method"]

        locked_count = (
            SubscriptionItem.objects.select_for_update().sunlight_active_count()
        )
        if locked_count >= settings.MAX_SUNLIGHT_SUBSCRIPTIONS:
            transaction.on_commit(
                lambda: add_to_waitlist.delay(organization.pk, plan.pk, request.user.pk)
            )
            messages.success(request, _("You have been added to the waitlist."))
            return redirect(request.path)
        transaction.on_commit(
            lambda: organization.add_subscription(
                selected_plan,
                None,
                request.user,
                token=stripe_token,
                payment_method=payment_method,
                nonprofit=result.get("nonprofit", False),
            )
        )
        return None

    def _handle_regular_subscription(self, request, result):
        """Call add_subscription directly; return error response or None on success."""
        # pylint: disable=too-many-return-statements
        organization = result["organization"]
        selected_plan = result["plan"]
        stripe_token = result["stripe_token"]
        payment_method = result["payment_method"]

        try:
            organization.add_subscription(
                selected_plan,
                None,
                request.user,
                token=stripe_token,
                payment_method=payment_method,
                nonprofit=result.get("nonprofit", False),
            )
            return None
        except PaymentActionRequired as exc:
            # SubscriptionItem saved but first invoice needs 3DS.
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
            return redirect(request.path)
        except SubscriptionError as exc:
            logger.error("Duplicate subscription attempt: %s", exc)
            if self._is_ajax():
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect(request.path)
        except stripe.StripeError as exc:
            logger.error(
                "Stripe error during subscription: %s",
                exc,
                exc_info=sys.exc_info(),
            )
            if self._is_ajax():
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect(request.path)


class PlanRedirectView(RedirectView):
    """
    Redirects legacy plan URLs to new org-scoped URL
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

            user = self.request.user
            protect_private_plan(plan, user)

            if user.is_anonymous:
                # A cached 301 would keep sending the user to log in after they had.
                self.permanent = False
                query = urlencode({"next": self.request.get_full_path()})
                return f"{reverse('account_login')}?{query}"
            if plan.for_individuals:
                url = reverse(
                    "users:plan",
                    kwargs={"username": user.username, "plan_slug": plan.slug},
                )
            else:
                # Redirect to checkout for the first org the user admins
                organization = (
                    Organization.objects.filter(
                        memberships__user=user,
                        memberships__admin=True,
                        individual=False,
                    )
                    .order_by("name")
                    .first()
                )
                if organization is None:
                    raise Http404("No organization found for this plan")
                url = reverse(
                    "organizations:plan",
                    kwargs={"slug": organization.slug, "plan_slug": plan.slug},
                )
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

    def log_staff_action(self, verb, description=None):
        """Record staff member actions for an accountability trail of changes
        made on someone else's behalf."""
        user = self.request.user
        organization = self.get_organization()
        if user.is_staff and not organization.has_admin(user):
            new_action(
                actor=user,
                verb=verb,
                target=organization,
                description=description,
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

        # One block per subscription, since cancellation is per subscription.
        subscriptions = []
        for subscription in self.object.subscriptions.prefetch_related(
            "items__plan", "items__plan_price"
        ).order_by("pk"):
            lines = list(subscription.items.all())
            if not lines:
                continue
            for line in lines:
                line.cost = (
                    line.price * line.quantity
                    if line.plan_price_id
                    else line.plan.cost(self.object.max_users)
                )
            subscriptions.append({"subscription": subscription, "lines": lines})
        context["subscriptions"] = subscriptions

        # Get card on file
        customer = self.object.customer()
        context["card_brand"] = customer.payment_brand
        context["card_last4"] = customer.payment_last4

        # Get receipt email — an organization may not have one set yet
        try:
            context["receipt_email"] = self.object.receipt_email
        except ReceiptEmail.DoesNotExist:
            context["receipt_email"] = None

        # Get five most recent payments
        payments = self.object.charges.order_by("-created_at").all()[:5]
        context["payments"] = payments

        return context


class BasePlans(SubscriptionObjectMixin, DetailView):
    """Browse plans page."""

    template_name = "subscriptions/browse_plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.object
        list_prices = PlanPrice.objects.filter(active=True, code="")
        plans = (
            Plan.objects.choices(organization)
            .filter(service__isnull=False, prices__in=list_prices)
            .distinct()
            .select_related("service")
            .prefetch_related(Prefetch("prices", queryset=list_prices), "entitlements")
        )

        held_tiers = {
            tier_of(slug)
            for slug in organization.subscription_items.values_list(
                "plan__slug", flat=True
            )
        }

        services = {}
        for plan in plans:
            plan.display_prices = self.get_display_prices(plan, organization.nonprofit)
            plan.nonprofit = any(
                price.label == "nonprofit" for price in plan.display_prices
            )
            plan.held = tier_of(plan.slug) in held_tiers
            plan.checkout_url = self.reverse_subject("plan", plan_slug=plan.slug)
            services.setdefault(plan.service, []).append(plan)
        for service_plans in services.values():
            service_plans.sort(
                key=lambda p: (self.monthly_cost(p.display_prices), p.name)
            )
        context["services"] = [
            {"service": service, "plans": services[service]}
            for service in sorted(services, key=lambda s: s.name)
        ]
        return context

    def get_display_prices(self, plan, nonprofit):
        """Get a plan's prices based on its nonprofit status."""

        by_variant = {
            (price.interval, price.label): price for price in plan.prices.all()
        }
        labels = ("nonprofit", "standard") if nonprofit else ("standard",)
        prices = []
        for interval in ("annual", "monthly"):
            for label in labels:
                if (interval, label) in by_variant:
                    prices.append(by_variant[interval, label])
                    break
        return prices

    def monthly_cost(self, prices):
        for price in prices:
            if price.interval == "monthly":
                return price.amount
        return prices[0].amount / 12


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
            self.log_staff_action("updated the payment method")
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
        # it would set up a failed renewal.  A free one never reaches Stripe.
        if (
            organization.subscriptions.filter(cancelled=False)
            .exclude(kind="free")
            .exists()
        ):
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

        self.log_staff_action("removed the payment method")
        success_msg = _("Credit card removed")
        if self._is_ajax():
            return JsonResponse({"redirect": redirect_url, "message": str(success_msg)})
        messages.success(request, success_msg)
        return redirect(redirect_url)


class BaseUpdateReceiptEmail(SubscriptionObjectMixin, UpdateView):
    form_class = UpdateReceiptEmailForm
    template_name = "subscriptions/update_receipt_email.html"

    def form_valid(self, form):
        try:
            self.object.set_billing_email(form.cleaned_data["receipt_email"])
            self.log_staff_action("updated the receipt email")
            return redirect(self.reverse_subject("subscriptions"))
        except stripe.StripeError as exc:
            # We can use Stripe's email validation here
            # pylint:disable=protected-access
            messages.error(self.request, exc._message)
            return redirect(self.reverse_subject("update-receipt-email"))

    def get_initial(self):
        try:
            return {"receipt_email": self.object.receipt_email.email}
        except ReceiptEmail.DoesNotExist:
            return {"receipt_email": ""}


class BaseCancelSubscription(SubscriptionObjectMixin, UpdateView):
    """Stop one plan: now with a credit while others bill, else at period end."""

    form_class = CancelSubscriptionForm
    template_name = "subscriptions/cancel_subscription.html"

    def get_line(self):
        return (
            self.object.subscription_items.filter(id=self.kwargs["pk"])
            .select_related("plan", "plan_price", "subscription")
            .first()
        )

    proration_signer = TimestampSigner(salt="squarelet.payments.removal-proration")

    def get_proration_date(self):
        """The moment the confirm page priced the credit at, if still usable.

        Signed, so it can't be backdated for a larger credit, and good for an
        hour.  Removing at the same moment makes the credit match what was shown.
        """
        try:
            return int(
                self.proration_signer.unsign(
                    self.request.POST.get("proration_date", ""), max_age=3600
                )
            )
        except (BadSignature, ValueError):
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        line = self.get_line()
        if line:
            # A property that queries the db for other lines, so read it once.
            removes_now = line.removes_now
            free = line.is_free
            context.update(
                plans=[line.plan.name],
                removes_now=removes_now,
                free=free,
                next_date=line.subscription.next_date,
            )
            if removes_now and not free:
                stamp = int(time.time())
                context["proration_date"] = self.proration_signer.sign(str(stamp))
                credit = line.removal_credit(stamp, removes_now)
                if credit:
                    context["credit"] = f"{credit / 100:,.2f}"
        return context

    def form_valid(self, form):
        line = self.get_line()
        if line is None:
            return redirect(self.reverse_subject("subscriptions"))
        next_date = line.subscription.next_date
        if line.subscription.cancelled:
            messages.info(self.request, _(f"This already ends on {next_date}."))
            return redirect(self.reverse_subject("subscriptions"))
        try:
            with transaction.atomic():
                removed = self.object.remove_subscription(
                    line,
                    user=self.request.user,
                    proration_date=self.get_proration_date(),
                )
        except stripe.StripeError as exc:
            messages.error(self.request, f"Stripe error: {format_stripe_error(exc)}")
            return redirect(self.reverse_subject("subscriptions"))
        if removed:
            self.log_staff_action("removed a plan", description=line.plan.name)
            messages.success(self.request, _(f"{line.plan.name} removed."))
        else:
            self.log_staff_action(
                "cancelled a subscription", description=line.plan.name
            )
            messages.success(
                self.request, _(f"Subscription cancelled.  It ends on {next_date}.")
            )
        return redirect(self.reverse_subject("subscriptions"))


class BaseEndSubscription(SubscriptionObjectMixin, UpdateView):
    """Cancel every plan on one subscription at period end."""

    form_class = CancelSubscriptionForm
    template_name = "subscriptions/cancel_subscription.html"

    def get_subscription(self):
        return self.object.subscriptions.filter(
            id=self.kwargs["pk"], kind="renewing"
        ).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subscription = self.get_subscription()
        if subscription:
            context["plans"] = [
                line.plan.name for line in subscription.items.select_related("plan")
            ]
            context["removes_now"] = False
            context["next_date"] = subscription.next_date
        return context

    def form_valid(self, form):
        subscription = self.get_subscription()
        if subscription and not subscription.cancelled:
            plans = self.object.end_subscription(subscription, user=self.request.user)
            self.log_staff_action(
                "cancelled a subscription",
                description=", ".join(plan.name for plan in plans),
            )
            messages.success(
                self.request,
                _(f"Subscription cancelled.  It ends on {subscription.next_date}."),
            )
        return redirect(self.reverse_subject("subscriptions"))


class BasePaymentsList(SubscriptionObjectMixin, ListView):
    template_name = "subscriptions/payments.html"
    paginate_by = 20

    def get_queryset(self):
        return Charge.objects.filter(organization=self.get_organization())

    def _payments_url(self, organization):
        """Reverse the payment history URL for an account the user can view.

        The personal account's pages live under the ``users`` namespace and
        are keyed on the member's username; organization pages are keyed on
        the org slug.
        """
        if organization.individual:
            return reverse(
                "users:payments", kwargs={"username": self.request.user.username}
            )
        return reverse("organizations:payments", kwargs={"slug": organization.slug})

    def get_nav_accounts(self, organization):
        """Build the sidebar nav across every account whose payments the user
        can view — their personal account and any organization they
        administer — flagging the one currently being viewed as active."""
        user = self.request.user
        organizations = [user.individual_organization]
        organizations += list(
            user.organizations.filter(individual=False, memberships__admin=True)
            .distinct()
            .order_by("name")
        )
        return [
            {
                "organization": org,
                "url": self._payments_url(org),
                "active": org.pk == organization.pk,
            }
            for org in organizations
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        context["organization"] = organization
        context["nav_accounts"] = self.get_nav_accounts(organization)
        return context


class BaseResubscribe(SubscriptionObjectMixin, View):
    """Resubscribe to a cancelled subscription."""

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _error(self, message, redirect_url="subscriptions"):
        """Return the error as JSON for AJAX callers, else flash and redirect."""
        if self._is_ajax():
            return JsonResponse({"error": str(message)}, status=400)
        messages.error(self.request, message)
        return redirect(self.reverse_subject(redirect_url))

    def post(self, request, *args, **kwargs):
        organization = self.get_object()
        redirect_url = self.reverse_subject("subscriptions")
        subscription = organization.subscription_items.filter(
            id=self.kwargs["pk"]
        ).first()
        try:
            subscription.uncancel()
        except ValidationError as exc:
            return self._error(exc.message, "update-card")
        except SubscriptionError as exc:
            return self._error(str(exc))
        except stripe.StripeError as exc:
            return self._error(f"Stripe error: {format_stripe_error(exc)}")

        self.log_staff_action("uncancelled subscription")
        success_msg = _(f"Resubscribed to {subscription.plan.name}")
        if self._is_ajax():
            return JsonResponse({"redirect": redirect_url, "message": str(success_msg)})
        messages.success(request, success_msg)
        return redirect(redirect_url)


def get_checkout_plan(organization, slug):
    """The plan `organization` may buy at `slug`, or 404."""
    return get_object_or_404(
        Plan.objects.choices(organization).select_related("service"), slug=slug
    )


class BasePlanCheckoutRedirect(SubscriptionObjectMixin, RedirectView):
    """Send a plan's checkout link on to its annual checkout, else monthly."""

    def get_redirect_url(self, *args, **kwargs):
        organization = self.get_organization()
        plan = get_checkout_plan(organization, self.kwargs["plan_slug"])
        interval = plan.default_interval(organization.nonprofit)
        if interval is None:
            raise Http404("This plan is not available")
        return self.reverse_subject(
            "plan-checkout", plan_slug=plan.slug, interval=interval
        )


class BasePlanCheckout(SubscriptionObjectMixin, DetailView):
    """Buy one plan at one interval with the payment method on file."""

    template_name = "subscriptions/plan_checkout.html"

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def get_plan(self):
        return get_checkout_plan(self.object, self.kwargs["plan_slug"])

    def get_prices(self, plan, interval):
        return plan.checkout_prices(interval, self.object.nonprofit)

    def get_price(self, plan):
        """The price this page sells, or 404."""
        interval = self.kwargs["interval"]
        if interval not in Plan.CHECKOUT_INTERVALS:
            raise Http404("No such billing interval")
        price, list_price = self.get_prices(plan, interval)
        if price is None:
            raise Http404("This plan is not sold at that interval")
        return price, list_price

    def is_held(self, plan):
        held = self.object.line_holding(plan)
        return held is not None and held.subscription.kind != "free"

    def get_organization_choices(self, plan, interval):
        """`(organization, checkout url)` for each account the user may switch to.

        The page's own organization comes first, so staff acting on someone
        else's account still see it selected.
        """
        if self.individual:
            return []

        user = self.request.user
        choices = [(self.object, self.request.path)]
        admin_orgs = (
            user.organizations.filter(memberships__admin=True)
            .exclude(pk=self.object.pk)
            .order_by("name")
        )
        for organization in admin_orgs:
            if not Plan.objects.choices(organization).filter(pk=plan.pk).exists():
                continue
            held = organization.line_holding(plan)
            if held is not None and held.subscription.kind != "free":
                continue
            if organization.individual:
                url = reverse(
                    "users:plan-checkout",
                    kwargs={
                        "username": user.username,
                        "plan_slug": plan.slug,
                        "interval": interval,
                    },
                )
            else:
                url = reverse(
                    "organizations:plan-checkout",
                    kwargs={
                        "slug": organization.slug,
                        "plan_slug": plan.slug,
                        "interval": interval,
                    },
                )
            choices.append((organization, url))
        return choices

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.object
        plan = self.get_plan()
        price, list_price = self.get_price(plan)
        context["organization_choices"] = self.get_organization_choices(
            plan, price.interval
        )

        other_interval = next(i for i in Plan.CHECKOUT_INTERVALS if i != price.interval)
        if self.get_prices(plan, other_interval)[0] is not None:
            context["other_interval_url"] = self.reverse_subject(
                "plan-checkout", plan_slug=plan.slug, interval=other_interval
            )

        held = self.is_held(plan)
        due_today = (
            None
            if held
            else SubscriptionItem.objects.due_on_start(organization, price) / 100
        )
        customer = organization.customer()
        context.update(
            plan=plan,
            benefits=plan.get_benefits(),
            price=price,
            # Struck through beside a nonprofit rate.
            list_price=(
                list_price if list_price and list_price.amount > price.amount else None
            ),
            due_today=due_today,
            prorated=due_today != price.amount,
            held=held,
            available=plan.has_available_slots(),
            card_brand=customer.payment_brand,
            card_last4=customer.payment_last4,
            card_form=CardForm(),
        )
        return context

    def _error(self, message):
        """Return the error as JSON for AJAX callers, else flash and redirect."""
        if self._is_ajax():
            return JsonResponse({"error": str(message)}, status=400)
        messages.error(self.request, message)
        return redirect(self.request.path)

    def join_waitlist(self, plan):
        """Put the organization on a full plan's waitlist and return to its plans."""
        organization, user = self.object, self.request.user
        redirect_url = self.reverse_subject("plans")
        # Wix must not hear of a waitlist entry the request then rolls back.
        transaction.on_commit(
            lambda: add_to_waitlist.delay(organization.pk, plan.pk, user.pk)
        )
        message = _("This plan is full. You have been added to its waitlist.")
        messages.success(self.request, message)
        if self._is_ajax():
            return JsonResponse({"redirect": redirect_url, "message": str(message)})
        return redirect(redirect_url)

    def post(self, request, *args, **kwargs):
        # pylint: disable=too-many-return-statements
        self.object = organization = self.get_object()
        plan = self.get_plan()
        price, _list_price = self.get_price(plan)
        redirect_url = self.reverse_subject("subscriptions")

        if self.is_held(plan):
            return self._error(_("You are already subscribed to this plan."))
        # Locked so two purchases cannot both take the last slot.
        if (
            plan.is_sunlight_plan
            and plan.wix
            and SubscriptionItem.objects.select_for_update().sunlight_active_count()
            >= settings.MAX_SUNLIGHT_SUBSCRIPTIONS
        ):
            return self.join_waitlist(plan)
        if organization.customer().default_payment_method_obj() is None:
            return self._error(_("Add a payment method before subscribing."))

        try:
            organization.add_subscription(
                plan,
                None,
                request.user,
                payment_method="card",
                nonprofit=price.label == "nonprofit",
                interval=price.interval,
            )
        except PaymentActionRequired as exc:
            if self._is_ajax():
                return JsonResponse(
                    {
                        "client_secret": exc.client_secret,
                        "payment_intent_id": exc.payment_intent_id,
                        "redirect": redirect_url,
                    },
                    status=402,
                )
            return self._error(
                _("Your card requires additional authentication. Please try again.")
            )
        except SubscriptionError as exc:
            return self._error(str(exc))
        except stripe.StripeError as exc:
            logger.error(
                "Stripe error during checkout: %s", exc, exc_info=sys.exc_info()
            )
            return self._error(f"Payment error: {format_stripe_error(exc)}")

        self.log_staff_action("subscribed to a plan", description=plan.name)
        success_msg = _(f"Subscribed to {plan.name}")
        messages.success(request, success_msg)
        if self._is_ajax():
            return JsonResponse({"redirect": redirect_url, "message": str(success_msg)})
        return redirect(redirect_url)
