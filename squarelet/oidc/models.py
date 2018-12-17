"""Models for the OIDC app"""

# Django
from django.db import models

# Standard Library
import hashlib
import hmac
import random
import time

# Third Party
import requests


def make_secret_key():
    # leave out easily confused characters: I,1,O,0
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(24))


class ClientProfile(models.Model):
    """Extra information for OIDC clients"""

    client = models.OneToOneField("oidc_provider.Client", on_delete=models.CASCADE)
    webhook_url = models.URLField(blank=True)

    def __str__(self):
        return str(self.client)

    def send_cache_invalidation(self, model, uuid):
        """Send a cache invalidation to this client"""
        timestamp = int(time.time())
        signature = hmac.new(
            key=self.client.client_secret.encode("utf8"),
            msg="{}{}{}".format(timestamp, model, uuid).encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        data = {
            "type": model,
            "uuid": uuid,
            "timestamp": timestamp,
            "signature": signature,
        }
        requests.post(self.webhook_url, data=data)
