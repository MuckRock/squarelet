# Standard Library
from hashlib import sha224
from random import randint
from uuid import uuid4

# Third Party
import factory


class ClientFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Client {n}")
    owner = factory.SubFactory("squarelet.users.tests.factories.UserFactory", is_staff=True)
    client_type = "confidential"
    client_id = factory.LazyFunction(lambda: str(randint(1, 999999)).zfill(6))
    client_secret = factory.LazyFunction(
        lambda: sha224(uuid4().hex.encode()).hexdigest()
    )
    website_url = factory.Faker("url")
    terms_url = factory.Faker("url")
    contact_email = factory.Faker("email")

    class Meta:
        model = "oidc_provider.Client"
