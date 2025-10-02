# Django
from django.utils import timezone

# Standard Library
from datetime import date

# Third Party
import factory
from autoslug.utils import slugify


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
            for plan in extracted:
                SubscriptionFactory(plan=plan, organization=self)


class IndividualOrganizationFactory(OrganizationFactory):
    individual = True
    private = True
    max_users = 1


class CustomerFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory",
        customer=factory.SelfAttribute("."),
    )
    customer_id = factory.Sequence(lambda n: f"customer-{n}")

    class Meta:
        model = "organizations.Customer"


class MembershipFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    admin = True

    class Meta:
        model = "organizations.Membership"


class SubscriptionFactory(factory.django.DjangoModelFactory):
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    plan = factory.SubFactory("squarelet.organizations.tests.factories.PlanFactory")
    update_on = factory.LazyFunction(date.today)

    class Meta:
        model = "organizations.Subscription"


class PlanFactory(factory.django.DjangoModelFactory):
    """A factory for creating Plan test objects"""

    name = factory.Sequence(lambda n: f"Plan {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    public = True

    class Meta:
        model = "organizations.Plan"
        django_get_or_create = ("name",)


class ProfessionalPlanFactory(PlanFactory):
    """A professional plan factory"""

    name = "Professional"
    minimum_users = 1
    base_price = 20
    price_per_user = 5
    for_groups = False


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


class InvitationRequestFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    request = True

    class Meta:
        model = "organizations.Invitation"


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
    subscription = factory.SubFactory(
        "squarelet.organizations.tests.factories.SubscriptionFactory"
    )
    amount = 10000  # $100.00 in cents
    due_date = factory.LazyFunction(date.today)
    status = "open"
    created_at = factory.LazyFunction(timezone.now)

    class Meta:
        model = "organizations.Invoice"
