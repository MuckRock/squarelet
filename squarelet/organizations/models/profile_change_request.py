"""Profile change request model"""

# Django
from django.db import models, transaction
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

# Third Party
from autoslug import AutoSlugField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.utils import create_zendesk_ticket
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.choices import (
    CHANGE_STATUS_CHOICES,
    COUNTRY_CHOICES,
    STATE_CHOICES,
)


class ProfileChangeRequest(models.Model):
    """
    A request to change core organization data, requiring staff approval
    """

    FIELDS = ("name", "slug", "city", "state", "country")

    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name=_("organization"),
        on_delete=models.CASCADE,
        related_name="profile_change_requests",
        help_text=_("The organization we want to update"),
    )

    user = models.ForeignKey(
        "users.User",
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="organization_change_requests",
        help_text=_("The user making the request"),
    )

    status = models.CharField(
        _("status"), choices=CHANGE_STATUS_CHOICES, default="pending"
    )

    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this request was created")
    )
    updated_at = AutoLastModifiedField(
        _("updated at"), help_text=_("When this request was last updated")
    )

    # these are change requests, so they can be blank
    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("The name of the organization"),
        blank=True,
    )
    slug = AutoSlugField(
        _("slug"),
        help_text=_("A unique slug for use in URLs"),
        blank=True,
    )

    # setting this adds an OrganizationUrl row
    url = models.URLField(blank=True)

    # location
    city = models.CharField(
        _("city"),
        max_length=100,
        blank=True,
    )
    state = models.CharField(
        _("state"),
        max_length=2,
        blank=True,
        choices=STATE_CHOICES,
    )
    country = models.CharField(
        _("country"),
        max_length=2,
        blank=True,
        choices=COUNTRY_CHOICES,
    )

    # snapshot the current state of the organization we're updating
    previous = models.JSONField(_("previous"), blank=True, editable=False)

    explanation = models.TextField(
        _("explanation"), blank=True, help_text="Reason for this proposed change"
    )

    # zendesk
    ticket_id = models.IntegerField(
        _("ticket_id"),
        blank=True,
        null=True,
        help_text="Ticket ID on Zendesk",
    )

    def __str__(self):
        return f"Request: {self.organization} by {self.user}"

    def save(self, *args, **kwargs):
        if not self.previous:
            self.previous = {
                field: getattr(self.organization, field) for field in self.FIELDS
            }

        # only create one ticket, and don't create tickets for staff changes
        if not self.ticket_id and not self.user.is_staff:
            description = render_to_string(
                "organizations/change_request.txt",
                {"user": self.user, "organization": self.organization, "change": self},
            )
            try:
                audit = create_zendesk_ticket(
                    subject=f"Change request: {self.organization}",
                    description=description,
                )
                self.ticket_id = audit.ticket.id
            except Exception:  # pylint: disable=broad-except
                # Silently fail if zendesk ticket creation fails
                pass

        super().save(*args, **kwargs)

    def accept(self):
        "Accept changes and keep a record"
        with transaction.atomic():
            self.status = "accepted"
            for field in self.FIELDS:
                if value := getattr(self, field):
                    setattr(self.organization, field, value)

            self.save()
            self.organization.save()

            transaction.on_commit(
                lambda: send_cache_invalidations("organization", self.organization.uuid)
            )

    def reject(self):
        "Say no but keep a record"
        self.status = "rejected"
        self.save()
