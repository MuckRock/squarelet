# Third Party
# Standard Library

# Django
from django.utils import timezone

import factory
from autoslug.utils import slugify


class OrganizationFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"org-{n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    plan = factory.SubFactory("squarelet.organizations.tests.factories.FreePlanFactory")
    next_plan = factory.LazyAttribute(lambda obj: obj.plan)

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


class IndividualOrganizationFactory(OrganizationFactory):
    individual = True
    private = True
    max_users = 1


class MembershipFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory("squarelet.users.tests.factories.UserFactory")
    organization = factory.SubFactory(
        "squarelet.organizations.tests.factories.OrganizationFactory"
    )
    admin = True

    class Meta:
        model = "organizations.Membership"


class PlanFactory(factory.django.DjangoModelFactory):
    """A factory for creating Plan test objects"""

    name = factory.Sequence(lambda n: f"Plan {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    public = True

    class Meta:
        model = "organizations.Plan"
        django_get_or_create = ("name",)


class FreePlanFactory(PlanFactory):
    """A free plan factory"""

    name = "Free"


class ProfessionalPlanFactory(PlanFactory):
    """A professional plan factory"""

    name = "Professional"
    minimum_users = 1
    base_price = 20
    price_per_user = 5
    feature_level = 1


class OrganizationPlanFactory(PlanFactory):
    """An organization plan factory"""

    name = "Organization"
    minimum_users = 5
    base_price = 100
    price_per_user = 10
    feature_level = 2


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
