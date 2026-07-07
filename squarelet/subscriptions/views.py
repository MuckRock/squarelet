# Django
from django.contrib import messages
from django.http.response import JsonResponse
from django.shortcuts import redirect
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
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Charge, Organization
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.subscriptions.forms import (
    CancelSubscriptionForm,
    CardForm,
    UpdateReceiptEmailForm,
    UpdateSubscriptionFrequencyForm,
)


class BaseManageSubscriptions(DetailView):
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


class BaseUpdateSubscriptionFrequency(UpdateView):
    form_class = UpdateSubscriptionFrequencyForm
    template_name = "subscriptions/update_subscription_frequency.html"

    def get_queryset(self):
        return Organization.objects.filter(slug=self.kwargs["slug"])

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return queryset.get()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscription = self.object.subscriptions.filter(id=self.kwargs["pk"]).first()
        context["subscription"] = subscription
        context["next_date"] = get_subscription_next_date(subscription)

        return context


class BaseUpdateCard(UpdateView):
    """Update the credit card on file for an organization."""

    form_class = CardForm
    template_name = "subscriptions/update_card.html"

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def form_valid(self, form):
        organization = self.object
        user = self.request.user
        redirect_url = reverse("organizations:subscriptions", args=[organization.slug])
        token = form.cleaned_data["stripe_token"]
        try:
            organization.save_card(token, user)
        except stripe.StripeError as exc:
            user_message = format_stripe_error(exc)
            if self._is_ajax():
                return JsonResponse({"error": user_message}, status=400)
            messages.error(self.request, f"Payment error: {user_message}")
            return redirect(organization)
        else:
            success_msg = _("Credit card updated")
            if self._is_ajax():
                return JsonResponse(
                    {"redirect": redirect_url, "message": str(success_msg)}
                )
            messages.success(self.request, success_msg)
        return redirect(organization)

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


class BaseUpdateReceiptEmail(UpdateView):
    form_class = UpdateReceiptEmailForm
    template_name = "subscriptions/update_receipt_email.html"

    def form_valid(self, form):
        self.object.set_receipt_emails(form.cleaned_data["receipt_emails"])
        return redirect("organizations:subscriptions", slug=self.object.slug)

    def get_initial(self):
        return {
            "receipt_emails": ", ".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class BaseCancelSubscription(UpdateView):
    form_class = CancelSubscriptionForm
    template_name = "subscriptions/cancel_subscription.html"

    def get_queryset(self):
        return Organization.objects.filter(slug=self.kwargs["slug"])

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return queryset.get()

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
        return redirect("organizations:subscriptions", slug=self.object.slug)


class BasePaymentsList(ListView):
    template_name = "subscriptions/payments.html"
    paginate_by = 20

    def get_queryset(self):
        return Charge.objects.filter(organization__slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = Organization.objects.get(slug=self.kwargs["slug"])
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
