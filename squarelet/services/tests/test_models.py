# Django
from django.test import TransactionTestCase

# Squarelet
from squarelet.services.models import Service

# Local
from .factories import ServiceFactory


class ServiceModelTest(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.service = ServiceFactory()

    def test_service_creation(self):
        self.assertIsInstance(self.service, Service)
        self.assertEqual(str(self.service), self.service.name)

    def test_service_fields(self):
        self.assertEqual(self.service.name, f"Service {self.service.pk}")
        self.assertEqual(self.service.slug, f"service-{self.service.pk}")
        self.assertTrue(self.service.description)
        self.assertTrue(self.service.provider_name)
        self.assertTrue(self.service.base_url)
        self.assertTrue(self.service.icon)

    def test_service_ordering(self):
        service1 = ServiceFactory(name="A Service")
        service2 = ServiceFactory(name="B Service")
        services = Service.objects.all()
        self.assertEqual(services[0], service1)
        self.assertEqual(services[1], service2)
