# Django
from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid
from datetime import date

# Third Party
from autoslug import AutoSlugField
from djchoices import ChoiceItem, DjangoChoices

# Local
from ..core.fields import AutoCreatedField, AutoLastModifiedField


class OrgType(DjangoChoices):
    free = ChoiceItem(0, _("Free"))
    pro = ChoiceItem(1, _("Pro"))
    basic = ChoiceItem(2, _("Basic"))
    plus = ChoiceItem(3, _("Plus"))


class Organization(models.Model):
    """Orginization to allow pooled requests and collaboration"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(_("name of organization"), max_length=255, unique=True)
    slug = AutoSlugField(_("slug"), populate_from="name")
    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    users = models.ManyToManyField(
        "users.User",
        through="organizations.OrganizationMembership",
        related_name="organizations",
    )

    org_type = models.IntegerField(
        _("organization type"), choices=OrgType.choices, default=OrgType.basic
    )
    individual = models.BooleanField(
        _("individual organization"),
        default=False,
        help_text=_("This organization is solely for the use of one user"),
    )
    private = models.BooleanField(_("private organization"), default=False)

    # Book keeping
    max_users = models.IntegerField(_("maximum users"), default=1)
    monthly_cost = models.IntegerField(
        _("monthly cost"), default=0, help_text="In cents"
    )
    date_update = models.DateField(
        _("date update"),
        default=date.today,
        help_text=_("Date when monthly requests are restored"),
    )
    ## MuckRock Book keeping
    requests_per_month = models.IntegerField(
        _("requests per month"),
        default=0,
        help_text=_("Number of requests this organization receives each month."),
    )
    monthly_requests = models.IntegerField(
        _("monthly requests"),
        default=0,
        help_text=_("How many recurring requests are left for this month."),
    )
    num_requests = models.IntegerField(
        _("number of requests"),
        default=0,
        help_text=_("How many non-recurring requests are left."),
    )
    ## DocCloud Book keeping
    pages_per_month = models.IntegerField(
        _("pages per month"),
        default=0,
        help_text=_("Number of pages this organization receives each month."),
    )
    monthly_pages = models.IntegerField(
        _("monthly pages"),
        default=0,
        help_text=_("How many recurring pages are left for this month."),
    )
    num_pages = models.IntegerField(
        _("number of pages"),
        default=0,
        help_text=_("How many non-recurring pages are left."),
    )

    # stripe
    customer_id = models.CharField(_("customer id"), max_length=255, blank=True)
    subscription_id = models.CharField(_("subscription id"), max_length=255, blank=True)
    payment_failed = models.BooleanField(_("payment failed"), default=False)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        """The url for this object"""
        return reverse("org:detail", kwargs={"slug": self.slug})


class OrganizationMembership(models.Model):
    """Through table for organization membership"""

    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE
    )
    admin = models.BooleanField(
        _("admin"),
        default=False,
        help_text="This user has administrative rights for this organization",
    )

    class Meta:
        unique_together = ("user", "organization")

    def __str__(self):
        return "Membership: {} in {}".format(self.user, self.organization)


class ReceiptEmail(models.Model):
    """An additional email address to send receipts to"""

    org = models.ForeignKey(
        "organizations.Organization",
        related_name="receipt_emails",
        on_delete=models.CASCADE,
    )
    email = models.EmailField(_("email"))

    def __str__(self):
        return "Receipt Email: <%s>" % self.email
