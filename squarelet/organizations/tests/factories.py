# Django
from django.utils import timezone

# Standard Library
import uuid
from datetime import date

# Third Party
import factory
from autoslug.utils import slugify


class OrganizationFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"org-{uuid.uuid4().hex[:8]}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))

    class Meta:
        model = "organizations.Organization"
        django_get_or_create = ("name",)

    @factory.post_generation
    def users(self, create, extracted, **kwargs):
        if create and extracted:
            for user in extracted:
                # Add unique_together check
                if not self.memberships.filter(user=user).exists():
                    MembershipFactory(user=user, organization=self, admin=False)

    @factory.post_generation
    def admins(self, create, extracted, **kwargs):
        if create and extracted:
            for user in extracted:
                # Add unique_together check
                if not self.memberships.filter(user=user).exists():
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
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    customer_id = factory.LazyFunction(
        lambda: f"cus_{uuid.uuid4().hex[:8]}"
    )

    class Meta:
        model = "organizations.Customer"


class MembershipFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(OrganizationFactory)
    admin = True

    class Meta:
        model = "organizations.Membership"
        django_get_or_create = ("user", "organization")


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
    charge_id = factory.Sequence(lambda n: f"ch_{n:06d}")

    class Meta:
        model = "organizations.Charge"


class EntitlementFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Entitlement {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    client = factory.SubFactory("squarelet.oidc.tests.factories.ClientFactory")
    description = factory.Sequence(lambda n: f"Description {n}")

    class Meta:
        model = "organizations.Entitlement"
