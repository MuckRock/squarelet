# Django
from django.core.files.base import ContentFile

# Third Party
import factory

# Squarelet
from squarelet.services.models import Service


class ServiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Service
        # Plans name their service by slug, so tests share one row per slug.
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Service {n}")
    slug = factory.Sequence(lambda n: f"service-{n}")
    description = factory.Faker("paragraph")
    provider_name = factory.Faker("company")
    base_url = factory.Faker("url")
    icon = factory.LazyFunction(
        lambda: ContentFile(b"dummy-image-content", name="test-image.png")
    )
