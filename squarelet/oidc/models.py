"""Models for the OIDC app"""

# Django
from django.db import models
from django.utils.translation import gettext_lazy as _

# Standard Library
import hashlib
import hmac
import time

# Third Party
import requests


class ClientProfile(models.Model):
    """Extra information for OIDC clients"""

    client = models.OneToOneField(
        verbose_name=_("client"),
        to="oidc_provider.Client",
        on_delete=models.CASCADE,
        help_text=_("OIDC provider client this profile provides extra data for"),
    )
    webhook_url = models.URLField(
        _("webhook URL"),
        blank=True,
        help_text=_("URL to send webhook notifications to for this client"),
    )
    source = models.CharField(
        _("source"),
        max_length=10,
        choices=(
            ("muckrock", _("MuckRock")),
            ("presspass", _("PressPass")),
        ),
        default="muckrock",
        help_text=_("Which application did this client originate from?"),
    )

    def __str__(self):
        return str(self.client)

    def send_cache_invalidation(self, model, uuids):
        """Send a cache invalidation to this client"""
        timestamp = int(time.time())
        uuid_str = "".join(str(u) for u in uuids)
        signature = hmac.new(
            key=self.client.client_secret.encode("utf8"),
            msg=f"{timestamp}{model}{uuid_str}".encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        data = {
            "type": model,
            "uuids": uuids,
            "timestamp": timestamp,
            "signature": signature,
        }
        requests.post(self.webhook_url, data=data, timeout=30)
