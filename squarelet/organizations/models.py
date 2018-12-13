# Django
from django.conf import settings
from django.core.mail import send_mail
from django.db import models, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid
from datetime import date

# Third Party
import stripe
from autoslug import AutoSlugField
from memoize import mproperty

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.oidc.utils import send_cache_invalidations

# Local
from .choices import Plan
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
from .exceptions import InsufficientRequestsError
from .querysets import InvitationQuerySet, OrganizationQuerySet

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = "2018-09-24"


class Organization(models.Model):
    """Orginization to allow pooled requests and collaboration"""

    objects = OrganizationQuerySet.as_manager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # XXX make this case insensitive?
    name = models.CharField(_("name"), max_length=255, unique=True)
    slug = AutoSlugField(_("slug"), populate_from="name", unique=True)
    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    users = models.ManyToManyField(
        "users.User", through="organizations.Membership", related_name="organizations"
    )

    plan = models.IntegerField(_("plan"), choices=Plan.choices, default=Plan.free)
    next_plan = models.IntegerField(
        _("next plan"),
        help_text=_("Type to switch to at next billing cycle"),
        choices=Plan.choices,
        default=Plan.free,
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
    number_requests = models.IntegerField(
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
    number_pages = models.IntegerField(
        _("number of pages"),
        default=0,
        help_text=_("How many non-recurring pages are left."),
    )

    # stripe
    customer_id = models.CharField(_("customer id"), max_length=255, blank=True)
    subscription_id = models.CharField(_("subscription id"), max_length=255, blank=True)
    payment_failed = models.BooleanField(_("payment failed"), default=False)

    class Meta:
        ordering = ("slug",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("organization", self.pk)
            )

    def get_absolute_url(self):
        """The url for this object"""
        return reverse("organizations:detail", kwargs={"slug": self.slug})

    # User Management
    def has_admin(self, user):
        """Is the given user an admin of this organization"""
        return self.users.filter(pk=user.pk, memberships__admin=True).exists()

    def has_member(self, user):
        """Is the user a member?"""
        return self.users.filter(pk=user.pk).exists()

    def user_count(self):
        """Count the number of users, including pending invitations"""
        return self.users.count() + self.invitations.get_pending().count()

    def add_creator(self, user):
        """Add user as the creator of the organization"""
        # add creator to the organization as an admin by default
        self.memberships.create(user=user, admin=True)
        # add the creators email as a receipt recipient by default
        self.receipt_emails.create(email=user.email)

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

    def set_subscription(self, token, plan, max_users):
        if self.individual:
            max_users = 1
        if token:
            self.save_card(token)

        if self.plan == Plan.free and plan != Plan.free:
            # create a subscription going from free to non-free
            self._create_subscription(self.customer, plan, max_users)
        elif self.plan != Plan.free and plan == Plan.free:
            # cancel a subscription going from non-free to free
            self._cancel_subscription()
        elif self.plan != Plan.free and plan != Plan.free:
            # modify a subscription going from non-free to non-free
            self._modify_subscription(plan, max_users)

    def _create_subscription(self, customer, plan, max_users):
        # must have card on file

        extra_users = max_users - MIN_USERS[plan]

        if plan == Plan.pro:
            stripe_plan = "pro"
            quantity = 1
        else:
            stripe_plan = "org"
            quantity = BASE_PRICE[plan] + extra_users * PRICE_PER_USER[plan]

        subscription = customer.subscriptions.create(
            items=[{"plan": stripe_plan, "quantity": quantity}]
        )

        requests_per_month = (
            BASE_REQUESTS[plan] + extra_users * EXTRA_REQUESTS_PER_USER[plan]
        )
        pages_per_month = BASE_PAGES[plan] + extra_users * EXTRA_PAGES_PER_USER[plan]

        self.plan = plan
        self.next_plan = plan
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
        self.next_plan = Plan.free
        self.save()

    def _modify_subscription(self, plan, max_users):
        # only for basic/plus accounts

        extra_users = max_users - MIN_USERS[plan]
        quantity = BASE_PRICE[plan] + extra_users * PRICE_PER_USER[plan]

        requests_per_month = (
            BASE_REQUESTS[plan] + extra_users * EXTRA_REQUESTS_PER_USER[plan]
        )
        pages_per_month = BASE_PAGES[plan] + extra_users * EXTRA_PAGES_PER_USER[plan]

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

        if plan == Plan.plus:
            # upgrade immediately
            self.plan = plan
            self.next_plan = plan
        else:
            # downgrade at end of billing cycle
            self.next_plan = plan

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
        # XXX make a charge object / api???
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
        # XXX remove
        self.charge(
            amount=PRICE_PER_REQUEST * number_requests,
            token=token,
            metadata={"action": "buy-requests", "amount": number_requests},
        )
        self.number_requests = F("number_requests") + number_requests
        self.save()

    def set_receipt_emails(self, emails):
        new_emails = set(emails)
        old_emails = {r.email for r in self.receipt_emails.all()}
        self.receipt_emails.filter(email__in=old_emails - new_emails).delete()
        ReceiptEmail.objects.bulk_create(
            [ReceiptEmail(organization=self, email=e) for e in new_emails - old_emails]
        )

    # Resource Management

    def make_requests(self, amount):
        """Deduct `amount` requests from this organization's balance"""
        # XXX remove
        request_count = {"monthly": 0, "regular": 0}
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=self.pk)

            request_count["monthly"] = min(amount, organization.monthly_requests)
            amount -= request_count["monthly"]

            request_count["regular"] = min(amount, organization.number_requests)
            amount -= request_count["regular"]

            if amount > 0:
                raise InsufficientRequestsError(amount)

            organization.monthly_requests -= request_count["monthly"]
            organization.number_requests -= request_count["regular"]
            organization.save()
            return request_count

    def return_requests(self, data):
        """Return requests to the organization's balance"""
        # XXX remove
        self.monthly_requests = F("monthly_requests") + data["return_monthly"]
        self.number_requests = F("number_requests") + data["return_regular"]
        self.save()


class Membership(models.Model):
    """Through table for organization membership"""

    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
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

    def save(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user_id)
            )

    def delete(self, *args, **kwargs):
        # pylint: disable=arguments-differ
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user_id)
            )


class ReceiptEmail(models.Model):
    """An additional email address to send receipts to"""

    organization = models.ForeignKey(
        "organizations.Organization",
        related_name="receipt_emails",
        on_delete=models.CASCADE,
    )
    email = models.EmailField(_("email"))
    # XXX add unique constraint

    def __str__(self):
        return "Receipt Email: <%s>" % self.email


class Invitation(models.Model):
    """An invitation for a user to join an organization"""

    objects = InvitationQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        related_name="invitations",
        on_delete=models.CASCADE,
    )
    uuid = models.UUIDField(_("uuid"), default=uuid.uuid4, editable=False)
    email = models.EmailField(_("email"))
    user = models.ForeignKey(
        "users.User",
        related_name="invitations",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )
    request = models.BooleanField(
        _("request"),
        help_text="Is this a request for an invitation from the user or an invitation "
        "to the user from an admin?",
        default=False,
    )
    created_at = AutoCreatedField(_("created at"))
    # NULL accepted_at signifies it has not been accepted yet
    accepted_at = models.DateTimeField(_("accepted_at"), blank=True, null=True)

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

    def accept(self, user=None):
        """Accept the invitation"""
        if self.user is None and user is None:
            raise ValueError(
                "Must give a user when accepting if invitation has no user"
            )
        with transaction.atomic():
            if self.user is None:
                self.user = user
            self.accepted_at = timezone.now()
            self.save()
            Membership.objects.create(organization=self.organization, user=self.user)
