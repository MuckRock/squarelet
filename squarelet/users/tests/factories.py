# Third Party
import factory
from allauth.account.models import EmailAddress

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
        if extracted:
            self.set_password(extracted)
            if create:
                self.save()

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        """Create individual organization membership"""
        # pylint: disable=unused-argument
        if create:
            MembershipFactory(user=self, organization=self.individual_organization)

    @factory.post_generation
    def email_verified(self, create, extracted, **kwargs):
        """Creates and verifies EmailAddress for user"""
        if create:
            email_address = EmailAddress.objects.create(
                user=self, email=self.email, primary=True, verified=bool(extracted)
            )
            self.email = email_address.email

    class Meta:
        model = "users.User"
        django_get_or_create = ("username",)


class ApplicationTokenFactory(factory.django.DjangoModelFactory):
    """Builds tokens through `ApplicationToken.generate` so the secret is hashed.
    The plaintext is available on the instance as `plaintext`."""

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"script-{n}")
    expires_in = None
    allow_staff = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        token, plaintext = model_class.generate(*args, **kwargs)
        token.plaintext = plaintext
        return token

    class Meta:
        model = "users.ApplicationToken"
