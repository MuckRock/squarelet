# Django
from django.conf import settings
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.core.mail import send_mail
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import get_current_timezone
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid
from datetime import date, datetime

# Third Party
import stripe
from autoslug import AutoSlugField
from dateutil.relativedelta import relativedelta
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.oidc.middleware import send_cache_invalidations

# Local
from .querysets import InvitationQuerySet, OrganizationQuerySet, PlanQuerySet

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = "2018-09-24"

DEFAULT_AVATAR = static("images/avatars/organization.png")


class Organization(models.Model):
    """Orginization to allow pooled requests and collaboration"""

    objects = OrganizationQuerySet.as_manager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # XXX make this case insensitive?
    name = models.CharField(_("name"), max_length=255, unique=True)
    slug = AutoSlugField(_("slug"), populate_from="name", unique=True)
    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    avatar = ImageField(_("avatar"), upload_to="org_avatars", blank=True)

    users = models.ManyToManyField(
        "users.User", through="organizations.Membership", related_name="organizations"
    )

    plan = models.ForeignKey(
        "organizations.Plan", on_delete=models.PROTECT, related_name="organizations"
    )
    next_plan = models.ForeignKey(
        "organizations.Plan",
        on_delete=models.PROTECT,
        related_name="pending_organizations",
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
    # XXX rename this?
    date_update = models.DateField(
        _("date update"),
        null=True,
        blank=True,
        help_text=_("Date when monthly requests are restored"),
    )

    # stripe
    customer_id = models.CharField(_("customer id"), max_length=255, blank=True)
    subscription_id = models.CharField(_("subscription id"), max_length=255, blank=True)
    # XXX sync this to client sites, so they can show a notification
    # XXX show a notification on here
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

    @property
    def avatar_url(self):
        if self.avatar and self.avatar.url.startswith("http"):
            return self.avatar.url
        elif self.avatar:
            return f"{settings.SQUARELET_URL}{self.avatar.url}"
        else:
            return DEFAULT_AVATAR

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

    @property
    def card_display(self):
        if self.card:
            return f"{self.card.brand}: {self.card.last4}"
        else:
            return ""

    def save_card(self, token):
        # XXX race condition with stripe?
        self.customer.source = token
        self.customer.save()
        send_cache_invalidations("organization", self.pk)

    def set_subscription(self, token, plan, max_users):
        if self.individual:
            max_users = 1
        if token:
            self.save_card(token)

        if self.plan.free() and not plan.free():
            # create a subscription going from free to non-free
            self._create_subscription(self.customer, plan, max_users)
        elif not self.plan.free() and plan.free():
            # cancel a subscription going from non-free to free
            self._cancel_subscription(plan)
        elif not self.plan.free() and not plan.free():
            # modify a subscription going from non-free to non-free
            self._modify_subscription(plan, max_users)
        # XXX free to free

    def _create_subscription(self, customer, plan, max_users):

        subscription = customer.subscriptions.create(
            items=[{"plan": plan.stripe_id, "quantity": max_users}],
            billing="send_invoice" if plan.annual else "charge_automatically",
        )

        self.plan = plan
        self.next_plan = plan
        self.max_users = max_users
        self.date_update = date.today() + relativedelta(months=1)
        self.subscription_id = subscription.id
        self.save()

    def _cancel_subscription(self, plan):
        # XXX check that subscription exists?
        self.subscription.cancel_at_period_end = True
        self.subscription.save()

        self.next_plan = plan
        # XXX this will never trigger next plan
        # date update needs to destruct itself on next update
        self.date_update = None
        self.save()

    def _modify_subscription(self, plan, max_users):

        stripe.Subscription.modify(
            self.subscription_id,
            cancel_at_period_end=False,
            items=[
                {
                    # pylint: disable=unsubscriptable-object
                    "id": self.subscription["items"]["data"][0].id,
                    "plan": plan.stripe_id,
                    "quantity": max_users,
                }
            ],
            billing="send_invoice" if plan.annual else "charge_automatically",
        )

        if plan.feature_level >= self.plan.feature_level:
            # upgrade immediately
            self.plan = plan
            self.next_plan = plan
        else:
            # downgrade at end of billing cycle
            self.next_plan = plan

        self.max_users = max_users

        self.save()

    def charge(self, amount, description, token=None):
        # XXX ?
        charge = Charge(amount=amount * 100, organization=self, description=description)
        charge.make_charge(token)

    def set_receipt_emails(self, emails):
        new_emails = set(emails)
        old_emails = {r.email for r in self.receipt_emails.all()}
        self.receipt_emails.filter(email__in=old_emails - new_emails).delete()
        ReceiptEmail.objects.bulk_create(
            [ReceiptEmail(organization=self, email=e) for e in new_emails - old_emails]
        )


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


class Plan(models.Model):
    """Plans that organizations can subscribe to"""

    objects = PlanQuerySet.as_manager()

    name = models.CharField(_("name"), max_length=255, unique=True)
    slug = AutoSlugField(_("slug"), populate_from="name", unique=True)

    minimum_users = models.PositiveSmallIntegerField(_("minimum users"), default=1)
    base_price = models.PositiveSmallIntegerField(_("base price"), default=0)
    price_per_user = models.PositiveSmallIntegerField(_("price per user"), default=0)

    # XXX only on clients?
    feature_level = models.PositiveSmallIntegerField(_("feature level"), default=0)

    public = models.BooleanField(_("public"), default=False)
    annual = models.BooleanField(
        _("annual"),
        default=False,
        help_text=_("Invoice this plan annually instead of charging monthly"),
    )
    for_individuals = models.BooleanField(
        _("for individuals"),
        default=True,
        help_text=_("Is this plan usable for individual organizations?"),
    )
    for_groups = models.BooleanField(
        _("for groups"),
        default=True,
        help_text=_("Is this plan usable for non-individual organizations?"),
    )

    def __str__(self):
        return self.name

    def free(self):
        return self.base_price == 0 and self.price_per_user == 0

    def cost(self, users):
        return self.base_price + (users - self.minimum_users) * self.price_per_user

    @property
    def stripe_id(self):
        """Namespace the stripe ID to not conflict with previous plans we have made"""
        return f"squarelet-{self.slug}"

    def make_stripe_plan(self):
        """Create the plan on stripe"""
        # XXX how to migrate customers???
        if not self.free():
            try:
                # set up the pricing for groups and individuals
                # convert dollar amounts to cents for stripe
                if self.for_groups:
                    kwargs = {
                        "billing_scheme": "tiered",
                        "tiers": [
                            {
                                "flat_amount": 100 * self.base_price,
                                "up_to": self.minimum_users,
                            },
                            {"unit_amount": 100 * self.price_per_user, "up_to": "inf"},
                        ],
                        "tiers_mode": "graduated",
                    }
                else:
                    kwargs = {
                        "billing_scheme": "per_unit",
                        "amount": 100 * self.base_price,
                    }
                stripe.Plan.create(
                    id=self.stripe_id,
                    currency="usd",
                    interval="year" if self.annual else "month",
                    product={"name": self.name, "unit_label": "Seats"},
                    **kwargs,
                )
            except stripe.error.InvalidRequestError:
                # if the plan already exists, just skip
                pass

    def delete_stripe_plan(self):
        """Remove a stripe plan"""
        try:
            plan = stripe.Plan.retrieve(id=self.stripe_id)
            # We also want to remove the associated product
            product = stripe.Product.retrieve(id=plan.product)
            plan.delete()
            product.delete()
        except stripe.error.InvalidRequestError:
            # if the plan or product do not exist, just skip
            pass


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

    class Meta:
        ordering = ("created_at",)

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

    def get_name(self):
        """Returns the name or email if no name is set"""
        if self.user is not None and self.user.name:
            return self.user.name
        else:
            return self.email


class ReceiptEmail(models.Model):
    """An email address to send receipts to"""

    organization = models.ForeignKey(
        "organizations.Organization",
        related_name="receipt_emails",
        on_delete=models.CASCADE,
    )
    email = models.EmailField(_("email"))
    # XXX add unique constraint

    def __str__(self):
        return "Receipt Email: <%s>" % self.email


class Charge(models.Model):
    """A payment charged to an organization through Stripe"""

    amount = models.PositiveSmallIntegerField(
        _("amount"), help_text=_("Amount in cents")
    )
    organization = models.ForeignKey(
        "organizations.Organization", related_name="charges", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(_("created at"))
    charge_id = models.CharField(_("charge_id"), max_length=255, unique=True)

    # type & quantity ??
    description = models.CharField(_("description"), max_length=255)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"${self.amount / 100:.2f} charge to {self.organization.name}"

    def make_charge(self, token=None):
        """Make the charge on stripe
        """
        customer = self.organization.customer
        if token:
            source = customer.sources.create(source=token)
        else:
            source = self.organization.card

        charge = stripe.Charge.create(
            amount=self.amount,
            currency="usd",
            customer=customer,
            description=self.description,
            source=source,
            metadata={"organization": self.organization.name},
        )
        if token:
            source.delete()
        self.charge_id = charge.id
        self.created_at = datetime.fromtimestamp(
            charge.created, tz=get_current_timezone()
        )
        self.save()

    @mproperty
    def charge(self):
        return stripe.Charge.retrieve(self.charge_id)

    @property
    def amount_dollars(self):
        return self.amount / 100.0

    def send_receipt(self):
        """Send receipt"""
        # XXX
        # Receipt(self).send()
        send_mail(
            "Receipt",
            f"This is a receipt for {self.description}",
            "info@muckrock.com",  # XXX make this a variable - use diff email?
            [r.email for r in self.organization.receipt_emails.all()],
        )
