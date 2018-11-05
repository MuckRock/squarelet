# Django
from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "squarelet.users"
    verbose_name = "Users"

    def ready(self):
        # pylint: disable=unused-variable
        from . import signals
        from . import syncers
