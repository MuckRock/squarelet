# Django
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
from datetime import datetime

# Third Party
import stripe

# Squarelet
from squarelet.organizations.querysets import InvoiceQuerySet


class Invoice(models.Model):
    """Track invoices from Stripe"""

    objects = InvoiceQuerySet.as_manager()

    invoice_id = models.CharField(
        _("invoice id"),
        max_length=255,
        unique=True,
        help_text=_("The invoice ID from Stripe"),
    )
    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="invoices",
        help_text=_("The organization this invoice belongs to"),
    )
    subscription = models.ForeignKey(
        verbose_name=_("subscription"),
        to="organizations.Subscription",
        on_delete=models.SET_NULL,
        related_name="invoices",
        null=True,
        blank=True,
        help_text=_("The subscription this invoice is for, if applicable"),
    )
    amount = models.PositiveIntegerField(
        _("amount"), help_text=_("Total amount in cents")
    )
    due_date = models.DateField(
        _("due date"), help_text=_("When payment is due"), null=True, blank=True
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=[
            ("draft", _("Draft")),
            ("open", _("Open")),
            ("paid", _("Paid")),
            ("uncollectible", _("Uncollectible")),
            ("void", _("Void")),
        ],
        default="draft",
        help_text=_("Current status of the invoice"),
    )
    created_at = models.DateTimeField(
        _("created at"), help_text=_("When the invoice was created")
    )
    updated_at = models.DateTimeField(
        _("updated at"), auto_now=True, help_text=_("Last modification time")
    )
    last_overdue_email_sent = models.DateField(
        _("last overdue email sent"),
        null=True,
        blank=True,
        help_text=_("Date when the last overdue warning email was sent"),
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        amount_display = (self.amount / 100) if self.amount is not None else 0
        return f"Invoice {self.invoice_id} - ${amount_display:.2f} ({self.status})"

    @property
    def amount_dollars(self):
        """Return the amount in dollars"""
        if self.amount is None:
            return 0.0
        return self.amount / 100.0

    @property
    def is_overdue(self):
        """Check if invoice is past due date"""
        if self.status == "open" and self.due_date:
            return timezone.now().date() > self.due_date
        return False

    @classmethod
    def create_or_update_from_stripe(
        cls, stripe_invoice, organization, subscription=None
    ):
        """Create or update an Invoice from Stripe data."""
        due_date = (
            datetime.fromtimestamp(
                stripe_invoice["due_date"], tz=get_current_timezone()
            ).date()
            if stripe_invoice["due_date"]
            else None
        )
        created_at = datetime.fromtimestamp(
            stripe_invoice["created"], tz=get_current_timezone()
        )
        return cls.objects.update_or_create(
            invoice_id=stripe_invoice["id"],
            defaults={
                "organization": organization,
                "subscription": subscription,
                "amount": stripe_invoice["amount_due"],
                "status": stripe_invoice["status"],
                "due_date": due_date,
                "created_at": created_at,
            },
        )

    def mark_uncollectible_in_stripe(self):
        """
        Mark this invoice as uncollectible in Stripe.

        This method uses a direct API request to work with older Stripe API
        versions (2018-09-24) that don't have the mark_uncollectible method
        on the Invoice object.

        Raises:
            stripe.error.StripeError: If the Stripe API call fails
        """
        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.api_version = "2018-09-24"

        stripe.api_requestor.APIRequestor().request(
            "post",
            f"/v1/invoices/{self.invoice_id}/mark_uncollectible",
            {},
        )
