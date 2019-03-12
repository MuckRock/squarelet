# Third Party
import factory

# Squarelet
from squarelet.organizations.tests.factories import (
    IndividualOrganizationFactory,
    MembershipFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    name = factory.Faker("name")
    individual_organization = factory.SubFactory(IndividualOrganizationFactory)

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """Sets password"""
        # pylint: disable=unused-argument
        if extracted:
            self.set_password(extracted)
            self.save()

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        """Create individual organization membership"""
        # pylint: disable=unused-argument
        if create:
            MembershipFactory(user=self, organization=self.individual_organization)

    class Meta:
        model = "users.User"
        django_get_or_create = ("username",)
