# Third Party
import factory
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.users.tests.factories import UserFactory


class EmailFactory(factory.django.DjangoModelFactory):
    email = factory.Sequence(lambda n: f"user-email-{n}@example.com")
    verified = False
    primary = factory.Sequence(lambda n: False if n > 0 else True)
    user = factory.SubFactory(UserFactory)

    class Meta:
        model = EmailAddress
        django_get_or_create = ("email",)
