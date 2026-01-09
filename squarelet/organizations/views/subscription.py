# Django
from django.conf import settings
from django.contrib import messages
from django.http.response import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, UpdateView
from django.contrib.auth.mixins import UserPassesTestMixin

# Standard Library
import json
import logging
import sys

# Third Party
import stripe
from django_weasyprint import WeasyTemplateResponseMixin

# Squarelet
from squarelet.core.utils import (
    format_stripe_error,
    get_stripe_dashboard_url,
)
from squarelet.organizations.forms import PaymentForm
from squarelet.organizations.mixins import OrganizationAdminMixin
from squarelet.organizations.models import Charge, Organization
from squarelet.organizations.tasks import (
    handle_charge_succeeded,
    handle_invoice_created,
    handle_invoice_failed,
    handle_invoice_finalized,
    handle_invoice_marked_uncollectible,
    handle_invoice_paid,
    handle_invoice_voided,
)

logger = logging.getLogger(__name__)


class UpdateSubscription(OrganizationAdminMixin, UpdateView):
    queryset = Organization.objects.filter(individual=False)
    form_class = PaymentForm
    template_name = "organizations/organization_payment.html"

    def form_valid(self, form):
        organization = self.object
        new_plan = form.cleaned_data.get("plan")
        try:
            organization.set_subscription(
                token=form.cleaned_data["stripe_token"],
                plan=new_plan,
                max_users=form.cleaned_data.get("max_users"),
                user=self.request.user,
            )
        except stripe.error.StripeError as exc:
            user_message = format_stripe_error(exc)
            messages.error(self.request, f"Payment error: {user_message}")
        else:
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            if form.cleaned_data.get("remove_card_on_file"):
                organization.remove_card()
                messages.success(self.request, _("Credit card removed"))
            else:
                messages.success(
                    self.request,
                    (
                        _("Plan Updated")
                        if organization.individual
                        else _("Organization Updated")
                    ),
                )
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["failed_receipt_emails"] = self.object.receipt_emails.filter(
            failed=True
        )
        return context

    def get_initial(self):
        return {
            "plan": self.object.plan,
            "max_users": self.object.max_users,
            "receipt_emails": "\n".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChargeDetail(UserPassesTestMixin, DetailView):
    queryset = Charge.objects.all()
    template_name = "organizations/email/receipt.html"

    def test_func(self):
        return self.get_object().organization.has_admin(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "Receipt"
        return context


class PDFChargeDetail(WeasyTemplateResponseMixin, ChargeDetail):
    """Subclass to view receipt as PDF"""

    pdf_filename = "receipt.pdf"


@csrf_exempt
def stripe_webhook(request):  # pylint: disable=too-many-branches
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
    except stripe.error.SignatureVerificationError as exception:
        logger.error(
            "Stripe Webhook: Signature Verification Error: %s",
            sig_header,
            exc_info=sys.exc_info(),
        )
        return HttpResponseBadRequest()
    # If we've made it this far, then the webhook message was successfully sent!
    # Now it's up to us to act on it.
    # https://docs.stripe.com/api/events/types

    # Log invoice-related webhooks with minimal noise
    if event_type.startswith("invoice."):
        invoice_id = event["data"]["object"].get("id")
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
    if event_type == "charge.succeeded":
        handle_charge_succeeded.delay(event["data"]["object"])
    elif event_type == "invoice.payment_failed":
        handle_invoice_failed.delay(event["data"]["object"])
    elif event_type == "invoice.created":
        handle_invoice_created.delay(event["data"]["object"])
    elif event_type == "invoice.finalized":
        handle_invoice_finalized.delay(event["data"]["object"])
    elif event_type == "invoice.paid":
        # Listening for invoice.paid ensures we handle payments that
        # when happen when users pay them through Stripe or when staff
        # manually mark them as paid through the Stripe dashboard
        handle_invoice_paid.delay(event["data"]["object"])
    elif event_type == "invoice.marked_uncollectible":
        handle_invoice_marked_uncollectible.delay(event["data"]["object"])
    elif event_type == "invoice.voided":
        handle_invoice_voided.delay(event["data"]["object"])
    return HttpResponse()
