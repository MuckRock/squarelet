# Django
from django.apps import AppConfig
from django.db.utils import ProgrammingError

# Third Party
from Cryptodome.PublicKey import RSA


class UsersConfig(AppConfig):
    name = "squarelet.users"
    verbose_name = "Users"

    def ready(self):
        # pylint: disable=unused-import, import-outside-toplevel
        # Django
        from django.conf import settings

        # Third Party
        from oidc_provider.models import RSAKey

        # Local
        from . import signals

        try:
            rsakey = RSAKey.objects.first()
            if rsakey:
                settings.SIMPLE_JWT["SIGNING_KEY"] = rsakey.key
                settings.SIMPLE_JWT["VERIFYING_KEY"] = (
                    RSA.import_key(rsakey.key).publickey().export_key()
                )
        except ProgrammingError:
            # skip if RSA Key is not found for some reason
            pass

        from allauth.account import signals as account_signals
        from allauth.mfa import signals as mfa_signals

        account_signals._add_email.disconnect(mfa_signals.on_add_email)
