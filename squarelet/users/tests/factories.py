# Third Party
import factory

# Squarelet
from squarelet.organizations.tests.factories import MembershipFactory


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    name = factory.Faker("name")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """Sets password"""
        # pylint: disable=unused-argument
        if extracted:
            self.set_password(extracted)
            self.save()

    @factory.post_generation
    def organization(self, create, extracted, **kwargs):
        """Create individual organization"""
        # pylint: disable=unused-argument
        if create:
            MembershipFactory(
                user=self, organization__individual=True, organization__id=self.pk
            )

    class Meta:
        model = "users.User"
        django_get_or_create = ("username",)
