# Django
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Invoice {self.invoice_id} - ${self.amount / 100:.2f} ({self.status})"

    @property
    def amount_dollars(self):
        """Return the amount in dollars"""
        return self.amount / 100.0

    @property
    def is_overdue(self):
        """Check if invoice is past due date"""
        if self.status == "open" and self.due_date:
            return timezone.now().date() > self.due_date
        return False
