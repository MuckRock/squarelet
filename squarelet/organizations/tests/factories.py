# Third Party
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
