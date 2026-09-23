# Django
from django.db.models import signals
from django.utils import timezone

# Standard Library
from datetime import date
from unittest.mock import patch

# Third Party
import factory
from autoslug.utils import slugify

# Squarelet
from squarelet.organizations.choices import InvitationRole, RelationshipType


class OrganizationFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"org-{n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    customer = factory.RelatedFactory(
        "squarelet.organizations.tests.factories.CustomerFactory", "organization"
    )
    allow_auto_join = False
    verified_journalist = True

    class Meta:
        model = "organizations.Organization"
        django_get_or_create = ("name",)

    @factory.post_generation
    def users(self, create, extracted, **kwargs):
        if create and extracted:
            for user in extracted:
                MembershipFactory(user=user, organization=self, admin=False)

    @factory.post_generation
    def admins(self, create, extracted, **kwargs):
        if create and extracted:
            for user in extracted:
                MembershipFactory(user=user, organization=self, admin=True)

    @factory.post_generation
    def plans(self, create, extracted, **kwargs):
        if create and extracted:
            subscription = SubscriptionFactory(organization=self)
            for plan in extracted:
                SubscriptionItemFactory(subscription=subscription, plan=plan)
            # Clear the memoized cache for the plan/subscription properties
            # since they may have been accessed before subscriptions were created
            for attr_name in list(vars(self).keys()):
                if "plan" in attr_name.lower() or "subscription" in attr_name.lower():
                    try:
                        delattr(self, attr_name)
                    except AttributeError:
                        pass


class IndividualOrganizationFactory(OrganizationFactory):
    individual = True
    private = False
    hidden = True
    max_users = 1


class CustomerFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory",
        customer=factory.SelfAttribute("."),
    )
    customer_id = factory.Sequence(lambda n: f"customer-{n}")

    class Meta:
        model = "organizations.Customer"


class PaymentMethodFactory(factory.django.DjangoModelFactory):
    customer = factory.SubFactory(
        "squarelet.organizations.tests.factories.CustomerFactory"
    )
    method_type = "card"
    brand = "Visa"
    last4 = "4242"
    exp_month = 12
    exp_year = 2030
    stripe_id = factory.Sequence(lambda n: f"pm_{n}")
    is_default = True

    class Meta:
        model = "organizations.PaymentMethod"


class MembershipFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    admin = True

    class Meta:
        model = "organizations.Membership"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to mock sync_wix during factory creation"""
        with patch("squarelet.organizations.tasks.sync_wix.delay"):
            return super()._create(model_class, *args, **kwargs)


class SubscriptionFactory(factory.django.DjangoModelFactory):
    """A Stripe subscription for one organization.

    Keyed on the billing shape the way production is: asking for a second
    subscription with the same interval and collection method returns the
    one that already exists, rather than tripping the unique constraint.
    """

    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    # Declared so django_get_or_create can key on them; both match the
    # model defaults.
    interval = "monthly"
    collection_method = "charge_automatically"

    class Meta:
        model = "organizations.Subscription"
        django_get_or_create = ("organization", "interval", "collection_method")


def _price_for_line(plan, interval):
    """The plan's list price at this interval, made only if absent.

    Reused rather than created every time: a test that sets up its own
    price for a plan would otherwise collide with one of these on
    `unique_active_plan_price`, and the collision would be the factory's
    fault rather than the test's.
    """
    # Local import: this module is imported for its factories, and the
    # models it builds import it back through the app registry.
    # pylint: disable=import-outside-toplevel
    # Squarelet
    from squarelet.organizations.models.payment import PlanPrice

    if plan is None or plan.pk is None:
        # `build()` makes an unsaved line from unsaved parts; there is no
        # database to look in and nothing will be written.
        return None

    existing = PlanPrice.objects.filter(
        plan=plan, interval=interval, label="standard", code="", active=True
    ).first()
    if existing is not None:
        return existing
    return PlanPriceFactory(plan=plan, interval=interval, amount=100 * plan.base_price)


class SubscriptionItemFactory(factory.django.DjangoModelFactory):
    """A line on a subscription.

    Pass `subscription__organization=` or `subscription__cancelled=` to steer
    the parent; a bare call builds one for you.

    Every line has a price, the way the column now requires - built on the
    line's own plan, at the interval its subscription bills, so the three
    agree without the caller having to say so.  Pass `plan_price=` to
    choose one; pass `plan=` alone and the price follows it.
    """

    subscription = factory.SubFactory(
        "squarelet.organizations.tests.factories.SubscriptionFactory"
    )
    plan = factory.SubFactory("squarelet.organizations.tests.factories.PlanFactory")
    plan_price = factory.LazyAttribute(
        lambda item: _price_for_line(item.plan, item.subscription.interval)
    )

    class Meta:
        model = "organizations.SubscriptionItem"


@factory.django.mute_signals(signals.pre_save, signals.post_save)
class PlanFactory(factory.django.DjangoModelFactory):
    """A factory for creating Plan test objects.

    Comes with a list price at its own interval, because every plan made
    through the app has had one since `make_stripe_plan` started creating
    them - and a line cannot be sold against a plan that has none.  The
    signals stay muted so nothing reaches Stripe; the price is written
    directly.

    A test that wants an unsellable plan deletes it: `plan.prices.all()
    .delete()`.
    """

    name = factory.Sequence(lambda n: f"Plan {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    public = True

    class Meta:
        model = "organizations.Plan"
        django_get_or_create = ("name",)

    @factory.post_generation
    def list_price(self, create, extracted, **kwargs):
        """The plan's standard price, unless the test brought its own."""
        # pylint: disable=unused-argument
        if not create or extracted is False:
            return
        interval = "annual" if self.annual else "monthly"
        if self.prices.filter(interval=interval, label="standard", code="").exists():
            return
        PlanPriceFactory(
            plan=self,
            interval=interval,
            label="standard",
            code="",
            amount=100 * self.base_price,
        )


class ProfessionalPlanFactory(PlanFactory):
    """A professional plan factory"""

    name = "Professional"
    minimum_users = 1
    base_price = 20
    price_per_user = 5
    for_groups = False


class PlanPriceFactory(factory.django.DjangoModelFactory):
    """A price under a plan.  Defaults to a paid monthly list price.

    Which means it has a Stripe Price, the way a real paid row does once
    `consolidate_stripe_products` has run - a paid row with a blank id is a
    half-finished state, and leaving it as the default had every test
    resolving through one.  A $0 price stays blank, because `ensure_stripe_price`
    never creates one for it.  Pass `stripe_price_id=""` explicitly to build
    the half-finished state on purpose.
    """

    plan = factory.SubFactory("squarelet.organizations.tests.factories.PlanFactory")
    interval = "monthly"
    label = "standard"
    code = ""
    amount = 10000
    currency = "usd"
    stripe_price_id = factory.LazyAttributeSequence(
        lambda price, n: "" if price.amount == 0 else f"price_factory{n}"
    )

    class Meta:
        model = "organizations.PlanPrice"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Update the plan's price at these terms rather than adding a second.

        A plan arrives from `PlanFactory` already holding a list price, so
        a test asking for one at the same terms means "make it look like
        this", not "make another" - which the active-price constraint
        refuses anyway.  Updating keeps the test's amount rather than
        silently handing back the default, which a plain get_or_create
        would do.
        """
        natural = {
            field: kwargs.pop(field)
            for field in ("plan", "interval", "label", "code")
            if field in kwargs
        }
        if set(natural) == {"plan", "interval", "label", "code"}:
            price, _created = model_class.objects.update_or_create(
                **natural, defaults=kwargs
            )
            return price
        return super()._create(model_class, *args, **natural, **kwargs)


class OrganizationPlanFactory(PlanFactory):
    """An organization plan factory"""

    name = "Organization"
    minimum_users = 5
    base_price = 100
    price_per_user = 10
    for_individuals = False


class InvitationFactory(factory.django.DjangoModelFactory):

    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    request = False

    class Meta:
        model = "organizations.Invitation"

    role = InvitationRole.member


class InvitationRequestFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    request = True

    class Meta:
        model = "organizations.Invitation"


class OrganizationInvitationFactory(factory.django.DjangoModelFactory):
    from_organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    to_organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    from_user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    closed_by_user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    relationship_type = RelationshipType.member
    request = False

    class Meta:
        model = "organizations.OrganizationInvitation"


class ChargeFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    description = factory.Sequence(lambda n: f"Description {n}")
    created_at = factory.LazyFunction(timezone.now)
    amount = 350

    class Meta:
        model = "organizations.Charge"


class EntitlementFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Entitlement {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    client = factory.SubFactory("squarelet.oidc.tests.factories.ClientFactory")
    description = factory.Sequence(lambda n: f"Description {n}")

    class Meta:
        model = "organizations.Entitlement"


class EntitlementGrantFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Grant {n}")
    description = factory.Sequence(lambda n: f"Grant description {n}")

    class Meta:
        model = "organizations.EntitlementGrant"

    @factory.post_generation
    def entitlements(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.entitlements.set(extracted)

    @factory.post_generation
    def organizations(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.organizations.set(extracted)


class EmailDomainFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    domain = factory.Sequence(lambda n: f"example{n}.com")

    class Meta:
        model = "organizations.OrganizationEmailDomain"
        django_get_or_create = ("domain",)


class InvoiceFactory(factory.django.DjangoModelFactory):
    invoice_id = factory.Sequence(lambda n: f"in_{n}")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    subscription = None  # Optional - can be set explicitly
    amount = 10000  # $100.00 in cents
    due_date = factory.LazyFunction(date.today)
    status = "open"
    created_at = factory.LazyFunction(timezone.now)

    class Meta:
        model = "organizations.Invoice"


class ProfileChangeRequestFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    status = "pending"

    class Meta:
        model = "organizations.ProfileChangeRequest"
