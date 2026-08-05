"""Models for the OIDC app"""

# Django
from django.db import models
from django.utils.translation import gettext_lazy as _

# Standard Library
import hashlib
import hmac
import logging
import time

# Third Party
import requests

logger = logging.getLogger(__name__)

# (connect, read) - a stuck TLS handshake should not pin a worker for the full
# read timeout
WEBHOOK_TIMEOUT = (5, 30)
# clients return full debug HTML on error, and a sustained outage logs this on
# every attempt of every broadcast - enough to identify the error, no more
ERROR_BODY_CHARS = 200
# Log every uuid for interactive saves, where the list itself is what you need to
# trace a delivery. Bulk jobs like restore_organization pass thousands at once.
UUID_LOG_THRESHOLD = 30
UUID_LOG_SAMPLE = 3


def get_elapsed_ms(start):
    """Return elapsed ms since start"""
    return int((time.monotonic() - start) * 1000)


def format_uuids(uuids):
    """Render a uuid list for logging, abbreviating bulk batches"""
    uuid_strs = [str(u) for u in uuids]
    if len(uuid_strs) <= UUID_LOG_THRESHOLD:
        return str(uuid_strs)
    remaining = len(uuid_strs) - UUID_LOG_SAMPLE
    return f"{uuid_strs[:UUID_LOG_SAMPLE]} +{remaining} more"


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
    checks_verification = models.BooleanField(
        _("checks verification"),
        default=False,
        help_text=_(
            "Whether this client gates features behind verification. "
            "When enabled, unverified users are shown an informational notice "
            "during authorization."
        ),
    )
    verification_notice = models.TextField(
        _("verification notice"),
        blank=True,
        help_text=_(
            "Explanation shown to unverified users describing what this client "
            "limits to verified journalists. Markdown formatting supported. "
            "Only used when 'checks verification' is enabled."
        ),
    )

    def __str__(self):
        return str(self.client)

    def send_cache_invalidation(self, model, uuids):
        """Send a cache invalidation to this client

        Returns the response on success. Raises requests.HTTPError on a non-2xx
        response and requests.RequestException on network failure.
        """
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

        start = time.monotonic()
        try:
            response = requests.post(
                self.webhook_url, data=data, timeout=WEBHOOK_TIMEOUT
            )
        except requests.RequestException as exc:
            logger.warning(
                "[CACHE-INVALIDATION] Network failure client=%s model=%s uuids=%s "
                "elapsed_ms=%d url=%s: %s",
                self.client.name,
                model,
                format_uuids(uuids),
                get_elapsed_ms(start),
                self.webhook_url,
                exc,
            )
            raise

        elapsed_ms = get_elapsed_ms(start)
        if not response.ok:
            # log at warning, not error: the task logs a single error once it has
            # exhausted its retries, so one failed delivery is one Sentry event
            logger.warning(
                "[CACHE-INVALIDATION] Rejected client=%s model=%s uuids=%s "
                "status=%d elapsed_ms=%d body=%s",
                self.client.name,
                model,
                format_uuids(uuids),
                response.status_code,
                elapsed_ms,
                response.text[:ERROR_BODY_CHARS],
            )
            response.raise_for_status()

        logger.info(
            "[CACHE-INVALIDATION] Sent client=%s model=%s count=%d status=%d "
            "elapsed_ms=%d uuids=%s",
            self.client.name,
            model,
            len(uuids),
            response.status_code,
            elapsed_ms,
            format_uuids(uuids),
        )
        return response
