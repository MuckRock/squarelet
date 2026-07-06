# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http.response import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

# Standard Library
import json
import logging
import sys
from datetime import datetime

# Third Party
import stripe
from django_weasyprint import WeasyTemplateResponseMixin

# Squarelet
from squarelet.core.utils import (
    format_stripe_error,
    get_stripe_dashboard_url,
    new_action,
)
from squarelet.organizations.forms import (
    CancelSubscriptionForm,
    CardForm,
    PaymentForm,
    UpdateReceiptEmailForm,
    UpdateSubscriptionFrequencyForm,
)
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Charge, Organization
from squarelet.organizations.models.payment import Plan
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.payments.exceptions import SubscriptionError
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.tasks import (
    handle_charge_succeeded,
    handle_customer_updated,
    handle_invoice_created,
    handle_invoice_failed,
    handle_invoice_finalized,
    handle_invoice_marked_uncollectible,
    handle_invoice_paid,
    handle_invoice_updated,
    handle_invoice_voided,
    handle_subscription_deleted,
    handle_subscription_updated,
)

logger = logging.getLogger(__name__)


class ManageSubscriptions(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_edit_subscription"
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managesubscriptions.html"

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


class UpdateSubscription(OrganizationPermissionMixin, UpdateView):
    permission_required = "organizations.can_edit_subscription"
    queryset = Organization.objects.filter(individual=False)
    form_class = PaymentForm
    template_name = "organizations/organization_payment.html"

    def _is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _apply_subscription_change(self, organization, current_plan, user, form):
        """Dispatch add/remove/modify based on current vs new plan."""
        token = form.cleaned_data["stripe_token"]
        new_plan = form.cleaned_data.get("plan")
        max_users = form.cleaned_data.get("max_users")

        if not current_plan and new_plan:
            organization.add_subscription(new_plan, max_users, user, token=token)
        elif current_plan and not new_plan:
            organization.remove_subscription(current_plan, user)
        elif current_plan and new_plan:
            if token:
                organization.save_card(token, user)
            organization.modify_subscription(current_plan, new_plan, max_users, user)

    def form_valid(self, form):
        # pylint: disable=too-many-return-statements
        organization = self.object
        user = self.request.user
        current_plan = organization.plans.first()
        redirect_url = organization.get_absolute_url()
        try:
            self._apply_subscription_change(organization, current_plan, user, form)
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
            messages.error(
                self.request,
                _("Your card requires additional authentication. Please try again."),
            )
            return redirect(organization)
        except SubscriptionError as exc:
            if self._is_ajax():
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(self.request, str(exc))
            return redirect(organization)
        except stripe.StripeError as exc:
            user_message = format_stripe_error(exc)
            if self._is_ajax():
                return JsonResponse({"error": user_message}, status=400)
            messages.error(self.request, f"Payment error: {user_message}")
            return redirect(organization)
        else:
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            if form.cleaned_data.get("remove_card_on_file"):
                organization.remove_payment_method()
                if self._is_ajax():
                    return JsonResponse(
                        {
                            "redirect": redirect_url,
                            "message": str(_("Credit card removed")),
                        }
                    )
                messages.success(self.request, _("Credit card removed"))
            else:
                # Log staff action to activity stream
                if self.request.user.is_staff:
                    new_action(
                        actor=self.request.user,
                        verb="updated organization subscription",
                        target=organization,
                    )
                success_msg = (
                    _("Plan Updated")
                    if organization.individual
                    else _("Organization Updated")
                )
                if self._is_ajax():
                    return JsonResponse(
                        {"redirect": redirect_url, "message": str(success_msg)}
                    )
                messages.success(self.request, success_msg)
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["failed_receipt_emails"] = self.object.receipt_emails.filter(
            failed=True
        )
        return context

    def get_initial(self):
        plan = self.object.plans.first()
        sub = self.object.subscriptions.filter(plan=plan).first() if plan else None
        max_users = sub.quantity if sub else self.object.max_users
        return {
            "plan": plan,
            "max_users": max_users,
            "receipt_emails": "\n".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class UpdateCard(OrganizationPermissionMixin, UpdateView):
    """Update the credit card on file for an organization."""

    permission_required = "organizations.can_edit_subscription"
    queryset = Organization.objects.filter(individual=False)
    form_class = CardForm
    template_name = "organizations/organization_updatecard.html"

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


class UpdateSubscriptionFrequency(OrganizationPermissionMixin, UpdateView):
    permission_required = "organizations.can_edit_subscription"
    queryset = Plan.objects.all()
    form_class = UpdateSubscriptionFrequencyForm
    template_name = "organizations/organization_updatesubscriptionfrequency.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "org"

        subscription = self.object.subscriptions.first()
        if subscription:
            context["organization"] = subscription.organization
            context["next_date"] = get_subscription_next_date(subscription)

        return context


class UpdateReceiptEmail(OrganizationPermissionMixin, UpdateView):
    permission_required = "organizations.can_edit_subscription"
    queryset = Organization.objects.filter(individual=False)
    form_class = UpdateReceiptEmailForm
    template_name = "organizations/organization_updatereceiptemail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "org"
        return context

    def form_valid(self, form):
        self.object.set_receipt_emails(form.cleaned_data["receipt_emails"])
        return redirect("organizations:subscriptions", slug=self.object.slug)

    def get_initial(self):
        return {
            "receipt_emails": ", ".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class CancelSubscription(OrganizationPermissionMixin, DeleteView):
    permission_required = "organizations.can_edit_subscription"
    queryset = Plan.objects.all()
    form_class = CancelSubscriptionForm
    template_name = "organizations/organization_cancelsubscription.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "org"

        subscription = self.object.subscriptions.first()
        if subscription:
            context["organization"] = subscription.organization
            context["next_date"] = get_subscription_next_date(subscription)

        return context


class PaymentsList(ListView):
    permission_required = "organizations.can_view_charge"
    template_name = "organizations/organization_payments.html"
    paginate_by = 20

    def get_queryset(self):
        return Charge.objects.filter(organization__slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "org"
        context["organization"] = Organization.objects.get(slug=self.kwargs["slug"])
        return context


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChargeDetail(UserPassesTestMixin, DetailView):
    queryset = Charge.objects.all()
    template_name = "organizations/email/receipt.html"

    def test_func(self):
        user = self.request.user
        org = self.get_object().organization
        return user.has_perm("organizations.can_view_charge", org)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "Receipt"
        # Show who the receipt was sent to — stored in metadata for new
        # charges, falling back to the org's current receipt emails for
        # older charges that predate this feature
        receipt_emails = self.object.metadata.get("receipt_emails")
        if receipt_emails is None:
            receipt_emails = list(
                self.object.organization.receipt_emails.values_list("email", flat=True)
            )
        context["receipt_emails"] = receipt_emails
        # Override user to None so the base email template does not show
        # the viewer's email in the "sent to" footer
        context["user"] = None
        return context


class PDFChargeDetail(WeasyTemplateResponseMixin, ChargeDetail):
    """Subclass to view receipt as PDF"""

    pdf_filename = "receipt.pdf"


@csrf_exempt
def stripe_webhook(request):
    """Handle webhooks from stripe"""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        if settings.STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        else:
            event = json.loads(request.body)

        event_type = event["type"]
    except (TypeError, ValueError, SyntaxError) as exception:
        logger.error(
            "Stripe Webhook: Error parsing JSON: %s", exception, exc_info=sys.exc_info()
        )
        return HttpResponseBadRequest()
    except KeyError as exception:
        logger.error(
            "Stripe Webhook: Unexpected structure: %s in %s",
            exception,
            event,
            exc_info=sys.exc_info(),
        )
        return HttpResponseBadRequest()
    except stripe.SignatureVerificationError as exception:
        logger.error(
            "Stripe Webhook: Signature Verification Error: %s",
            sig_header,
            exc_info=sys.exc_info(),
        )
        return HttpResponseBadRequest()
    # If we've made it this far, then the webhook message was successfully sent!
    # Now it's up to us to act on it.
    # https://docs.stripe.com/api/events/types

    # Convert to a plain dict so Celery can serialize it regardless of stripe version
    event_obj = event["data"]["object"]
    if hasattr(event_obj, "to_dict"):
        event_obj = event_obj.to_dict()

    # Log invoice-related webhooks with minimal noise
    if event_type.startswith("invoice."):
        invoice_id = event_obj.get("id")
        if invoice_id:
            stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
            logger.info(
                "[STRIPE-WEBHOOK] %s: %s (%s)",
                event_type,
                invoice_id,
                stripe_link,
            )
        else:
            logger.info("[STRIPE-WEBHOOK] %s (no invoice ID)", event_type)
    else:
        # For non-invoice events, log with more detail
        success_msg = (
            "[STRIPE-WEBHOOK] Received Stripe webhook\n"
            "\tfrom:\t%(address)s\n"
            "\ttype:\t%(type)s\n"
            "\tdata:\t%(data)s\n"
        ) % {"address": request.META["REMOTE_ADDR"], "type": event_type, "data": event}
        logger.info(success_msg)
    # Map event types to their handler tasks
    # invoice.paid ensures we handle payments when users pay through
    # Stripe or when staff manually mark them as paid
    event_handlers = {
        "charge.succeeded": handle_charge_succeeded,
        "customer.updated": handle_customer_updated,
        "customer.subscription.updated": handle_subscription_updated,
        "customer.subscription.deleted": handle_subscription_deleted,
        "invoice.payment_failed": handle_invoice_failed,
        "invoice.created": handle_invoice_created,
        "invoice.updated": handle_invoice_updated,
        "invoice.finalized": handle_invoice_finalized,
        "invoice.paid": handle_invoice_paid,
        "invoice.marked_uncollectible": handle_invoice_marked_uncollectible,
        "invoice.voided": handle_invoice_voided,
    }
    handler = event_handlers.get(event_type)
    if handler:
        handler.delay(event_obj)
    return HttpResponse()


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
