# Django
from django.utils import timezone

# Standard Library
from datetime import date

# Third Party
import factory
from autoslug.utils import slugify

# Squarelet
from squarelet.organizations.choices import StripeAccounts


class OrganizationFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"org-{n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    customer = factory.RelatedFactory(
        "squarelet.organizations.tests.factories.CustomerFactory", "organization"
    )

    class Meta:
        model = "organizations.Organization"
        django_get_or_create = ("name",)

    @factory.post_generation
    def users(self, create, extracted, **kwargs):
        # pylint: disable=unused-argument
        if create and extracted:
            for user in extracted:
                MembershipFactory(user=user, organization=self, admin=False)

    @factory.post_generation
    def admins(self, create, extracted, **kwargs):
        # pylint: disable=unused-argument
        if create and extracted:
            for user in extracted:
                MembershipFactory(user=user, organization=self, admin=True)

    @factory.post_generation
    def plans(self, create, extracted, **kwargs):
        # pylint: disable=unused-argument
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
    stripe_account = StripeAccounts.muckrock
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
