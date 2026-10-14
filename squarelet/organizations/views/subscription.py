# Django
from django.conf import settings
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin
from django.db.models import Prefetch
from django.http.response import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView

# Standard Library
import json
import logging
import sys

# Third Party
import stripe
from django_weasyprint import WeasyTemplateResponseMixin

# Squarelet
from squarelet.core.utils import get_stripe_dashboard_url
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Charge, Plan, PlanPrice
from squarelet.organizations.plan_mapping import tier_of
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
    handle_payment_method_attached,
    handle_payment_method_detached,
    handle_payment_method_updated,
    handle_subscription_deleted,
    handle_subscription_updated,
)
from squarelet.payments.views import (
    BaseCancelSubscription,
    BaseEndSubscription,
    BaseManageSubscriptions,
    BasePaymentsList,
    BaseRemoveCard,
    BaseResubscribe,
    BaseUpdateCard,
    BaseUpdateReceiptEmail,
    SubscriptionObjectMixin,
)

logger = logging.getLogger(__name__)


class OrgSubscriptionView(OrganizationPermissionMixin):
    """Base class for org subscription views."""

    subject = "organizations"
    individual = False
    permission_required = "organizations.can_edit_subscription"


class ManageSubscriptions(OrgSubscriptionView, BaseManageSubscriptions):
    pass


class Plans(OrgSubscriptionView, SubscriptionObjectMixin, DetailView):
    """Browse plans page."""

    template_name = "organizations/organization_plans.html"

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


class UpdateCard(OrgSubscriptionView, BaseUpdateCard):
    pass


class RemoveCard(OrgSubscriptionView, BaseRemoveCard):
    pass


class UpdateReceiptEmail(OrgSubscriptionView, BaseUpdateReceiptEmail):
    pass


class CancelSubscription(OrgSubscriptionView, BaseCancelSubscription):
    pass


class EndSubscription(OrgSubscriptionView, BaseEndSubscription):
    pass


class Resubscribe(OrgSubscriptionView, BaseResubscribe):
    pass


class PaymentsList(PermissionRequiredMixin, BasePaymentsList):
    subject = "organizations"
    individual = False

    def has_permission(self):
        user = self.request.user
        return user.has_perm("organizations.can_view_charge", self.get_organization())


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChargeDetail(UserPassesTestMixin, DetailView):
    queryset = Charge.objects.all()
    template_name = "organizations/email/receipt.html"

    def test_func(self):
        user = self.request.user
        org = self.get_object().organization
        return user.has_perm("organizations.can_view_charge", org)

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.receipt_pdf:
            return HttpResponseRedirect(obj.receipt_pdf.url)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "Receipt"
        # Show who the receipt was sent to — stored in metadata for new
        # charges, falling back to the org's current billing email for
        # older charges that predate this feature
        receipt_emails = self.object.metadata.get("receipt_emails")
        if receipt_emails is None:
            org_email = self.object.organization.email
            receipt_emails = [org_email] if org_email else []
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
        "payment_method.attached": handle_payment_method_attached,
        "payment_method.automatically_updated": handle_payment_method_updated,
        "payment_method.detached": handle_payment_method_detached,
        "payment_method.updated": handle_payment_method_updated,
    }
    handler = event_handlers.get(event_type)
    if handler:
        handler.delay(event_obj)
    return HttpResponse()
