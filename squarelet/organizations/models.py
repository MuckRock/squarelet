# Django
from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.db.models import F
from django.db.models.functions import Greatest
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid
from datetime import date

# Third Party
import stripe
from autoslug import AutoSlugField
from memoize import mproperty

# Local
from ..core.fields import AutoCreatedField, AutoLastModifiedField
from .choices import OrgType
from .constants import (
    BASE_PAGES,
    BASE_PRICE,
    BASE_REQUESTS,
    EXTRA_PAGES_PER_USER,
    EXTRA_REQUESTS_PER_USER,
    MIN_USERS,
    PRICE_PER_REQUEST,
    PRICE_PER_USER,
)

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = "2018-09-24"


class Organization(models.Model):
    """Orginization to allow pooled requests and collaboration"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(_("name"), max_length=255, unique=True)
    slug = AutoSlugField(_("slug"), populate_from="name")
    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    users = models.ManyToManyField(
        "users.User",
        through="organizations.OrganizationMembership",
        related_name="organizations",
    )

    org_type = models.IntegerField(
        _("organization type"), choices=OrgType.choices, default=OrgType.free
    )
    next_org_type = models.IntegerField(
        _("next organization type"),
        help_text=_("Type to switch to at next billing cycle"),
        choices=OrgType.choices,
        default=OrgType.basic,
    )
    individual = models.BooleanField(
        _("individual organization"),
        default=False,
        help_text=_("This organization is solely for the use of one user"),
    )
    private = models.BooleanField(_("private organization"), default=False)

    # Book keeping
    max_users = models.IntegerField(_("maximum users"), default=5)
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
        return reverse("organizations:detail", kwargs={"slug": self.slug})

    # User Management
    def is_admin(self, user):
        """Is the given user an admin of this organization"""
        return self.users.filter(
            pk=user.pk, organizationmembership__admin=True
        ).exists()

    # Payment Management
    @mproperty
    def customer(self):
        """Retrieve the customer from Stripe or create one if it doesn't exist"""
        if self.customer_id:
            try:
                return stripe.Customer.retrieve(self.customer_id)
            except stripe.error.InvalidRequestError:
                pass

        customer = stripe.Customer.create(
            description=self.users.first().username if self.individual else self.name
        )
        self.customer_id = customer.id
        self.save()
        return customer

    @mproperty
    def subscription(self):
        if self.subscription_id:
            try:
                return stripe.Subscription.retrieve(self.subscription_id)
            except stripe.error.InvalidRequestError:
                return None
        else:
            return None

    @mproperty
    def card(self):
        """Retrieve the customer's default credit card on file, if there is one"""
        if self.customer.default_source:
            return self.customer.sources.retrieve(self.customer.default_source)
        else:
            return None

    def save_card(self, token):
        self.customer.source = token
        self.customer.save()

    def set_subscription(self, token, org_type, max_users):
        if self.individual:
            max_users = 1
        if token:
            self.save_card(token)

        if self.org_type == OrgType.free and org_type != OrgType.free:
            # create a subscription going from free to non-free
            self._create_subscription(self.customer, org_type, max_users)
        elif self.org_type != OrgType.free and org_type == OrgType.free:
            # cancel a subscription going from non-free to free
            self._cancel_subscription()
        elif self.org_type != OrgType.free and org_type != OrgType.free:
            # modify a subscription going from non-free to non-free
            self._modify_subscription(org_type, max_users)

    def _create_subscription(self, customer, org_type, max_users):
        # must have card on file

        extra_users = max_users - MIN_USERS[org_type]

        if org_type == OrgType.pro:
            plan = "pro"
            quantity = 1
        else:
            plan = "org"
            quantity = BASE_PRICE[org_type] + extra_users * PRICE_PER_USER[org_type]

        subscription = customer.subscriptions.create(
            items=[{"plan": plan, "quantity": quantity}]
        )

        requests_per_month = (
            BASE_REQUESTS[org_type] + extra_users * EXTRA_REQUESTS_PER_USER[org_type]
        )
        pages_per_month = (
            BASE_PAGES[org_type] + extra_users * EXTRA_PAGES_PER_USER[org_type]
        )

        self.org_type = org_type
        self.next_org_type = org_type
        self.max_users = max_users
        self.date_update = date.today()
        self.requests_per_month = requests_per_month
        self.monthly_requests = requests_per_month
        self.pages_per_month = pages_per_month
        self.monthly_pages = pages_per_month
        self.subscription_id = subscription.id
        self.save()

    def _cancel_subscription(self):
        self.subscription.cancel_at_period_end = True
        self.subscription.save()
        self.next_org_type = OrgType.free
        self.save()

    def _modify_subscription(self, org_type, max_users):
        # only for basic/plus accounts

        extra_users = max_users - MIN_USERS[org_type]
        quantity = BASE_PRICE[org_type] + extra_users * PRICE_PER_USER[org_type]

        requests_per_month = (
            BASE_REQUESTS[org_type] + extra_users * EXTRA_REQUESTS_PER_USER[org_type]
        )
        pages_per_month = (
            BASE_PAGES[org_type] + extra_users * EXTRA_PAGES_PER_USER[org_type]
        )

        stripe.Subscription.modify(
            self.subscription_id,
            cancel_at_period_end=False,
            items=[
                {
                    # pylint: disable=unsubscriptable-object
                    "id": self.subscription["items"]["data"][0].id,
                    "plan": "org",
                    "quantity": quantity,
                }
            ],
        )

        if org_type == OrgType.plus:
            # upgrade immediately
            self.org_type = org_type
            self.next_org_type = org_type
        else:
            # downgrade at end of billing cycle
            self.next_org_type = org_type

        self.max_users = max_users

        # if new limit is higher than the old limit, add them immediately
        # use f expressions to avoid race conditions
        self.monthly_requests = F("monthly_requests") + Greatest(
            requests_per_month - F("requests_per_month"), 0
        )
        self.requests_per_month = requests_per_month

        self.monthly_pages = F("monthly_pages") + Greatest(
            pages_per_month - F("pages_per_month"), 0
        )
        self.pages_per_month = pages_per_month

        self.save()

    def charge(self, amount, token, metadata=None):
        if metadata is None:
            metadata = {}
        metadata["organization"] = self.name
        if token:
            source = token
            customer = None
        else:
            source = self.card
            customer = self.customer
        stripe.Charge.create(
            # convert amount from dollars to cents
            amount=amount * 100,
            currency="usd",
            source=source,
            customer=customer,
            metadata=metadata,
        )

    def buy_requests(self, number_requests, token):
        self.charge(
            amount=PRICE_PER_REQUEST * number_requests,
            token=token,
            metadata={"action": "buy-requests", "amount": number_requests},
        )
        self.num_requests = F("num_requests") + number_requests
        self.save()

    # Resource Management


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

    organization = models.ForeignKey(
        "organizations.Organization",
        related_name="receipt_emails",
        on_delete=models.CASCADE,
    )
    email = models.EmailField(_("email"))

    def __str__(self):
        return "Receipt Email: <%s>" % self.email


class Invitation(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        related_name="invitations",
        on_delete=models.CASCADE,
    )
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    email = models.EmailField()
    user = models.ForeignKey(
        "users.User",
        related_name="invitations",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_(
            "The user who accepted this invitation - NULL means it has not been "
            "accepted yet"
        ),
    )

    def __str__(self):
        return f"Invitation: {self.uuid}"

    def send(self):
        # XXX custom email class
        link = reverse("organizations:invitation", kwargs={"uuid": self.uuid})
        send_mail(
            f"Invitation to join {self.organization.name}",
            f"Click here to join: {settings.SQUARELET_URL}{link}",
            "info@muckrock.com",  # XXX make this a variable - use diff email?
            [self.email],
        )
