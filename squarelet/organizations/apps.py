# Django
from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    name = "squarelet.organizations"
    verbose_name = "Organizations"

    def ready(self):
        # pylint: disable=unused-variable
        from . import signals
