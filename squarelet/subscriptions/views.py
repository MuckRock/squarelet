# Django
from django.contrib import messages
from django.http.response import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, UpdateView

# Standard Library
from datetime import datetime

# Third Party
import stripe

# Squarelet
from squarelet.core.utils import format_stripe_error
from squarelet.organizations.models import Charge, Organization
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.subscriptions.forms import (
    CancelSubscriptionForm,
    CardForm,
    UpdateReceiptEmailForm,
    UpdateSubscriptionFrequencyForm,
)


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
        if customer.card is None:
            card = None
        elif customer.card.object == "payment_method":
            card = customer.card.card
        else:
            card = customer.card
        context["card"] = card

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
        if customer.card is None:
            card = None
        elif customer.card.object == "payment_method":
            card = customer.card.card
        else:
            card = customer.card
        context["card"] = card
        return context


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
