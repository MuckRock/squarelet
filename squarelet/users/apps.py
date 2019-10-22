# Django
from django.apps import AppConfig

# Third Party
from Cryptodome.PublicKey import RSA


class UsersConfig(AppConfig):
    name = "squarelet.users"
    verbose_name = "Users"

    def ready(self):
        # pylint: disable=unused-import
        from . import signals
        from django.conf import settings
        from oidc_provider.models import RSAKey

        rsakey = RSAKey.objects.first()
        settings.SIMPLE_JWT["SIGNING_KEY"] = rsakey.key
        settings.SIMPLE_JWT["VERIFYING_KEY"] = (
            RSA.import_key(rsakey.key).publickey().export_key()
        )
