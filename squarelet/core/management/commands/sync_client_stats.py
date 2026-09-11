# Django
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Standard Library
import logging

# Third Party
import requests
from rest_framework_simplejwt.tokens import AccessToken

# Squarelet
from squarelet.core.utils import requests_retry_session
from squarelet.organizations.models import Organization
from squarelet.users.models import User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Sync per-user and per-org stats from client services into client_stats.

    Pages each client's stats_api list endpoints,
    authenticating with a Squarelet-minted JWT for the configured service
    account, and merges each page into the matching entities' client_stats JSON
    under the client's key. Pages are merged as they arrive so the full result
    set is never held in memory. A fetched row whose UUID has no matching
    Accounts entity (e.g. a DocumentCloud account pre-merger that never logged back in)
    is skipped and reported, not merged. A failure syncing one client
    is logged and does not prevent syncing the others.
    """

    help = "Sync user and org stats from DocumentCloud and MuckRock"

    def handle(self, *args, **options):
        if not settings.STATS_SERVICE_USERNAME:
            raise CommandError("STATS_SERVICE_USERNAME is not configured")
        try:
            self.service_user = User.objects.get(
                username=settings.STATS_SERVICE_USERNAME
            )
        except User.DoesNotExist:
            raise CommandError(
                f"Service user '{settings.STATS_SERVICE_USERNAME}' not found"
            )

        self.session = requests_retry_session()
        self.session.headers.update({"User-Agent": "Accounts Stats Sync"})

        clients = {
            "documentcloud": settings.DOCCLOUD_STATS_API_URL,
            "muckrock": settings.MUCKROCK_STATS_API_URL,
        }
        for client, base_url in clients.items():
            try:
                self.stdout.write(f"Syncing {client}...")
                n_users, unmatched_users = self._sync_endpoint(
                    f"{base_url}users/", client, User, "individual_organization_id"
                )
                n_orgs, unmatched_orgs = self._sync_endpoint(
                    f"{base_url}organizations/", client, Organization, "uuid"
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{client}: {n_users:,} users "
                        f"({len(unmatched_users)} unmatched), "
                        f"{n_orgs:,} orgs ({len(unmatched_orgs)} unmatched)"
                    )
                )
            except (requests.RequestException, CommandError) as exc:
                # One client failing (down, auth misconfigured, network) must not
                # block syncing the others.
                logger.error("[stats sync] %s failed: %s", client, exc)
                self.stderr.write(self.style.ERROR(f"{client}: sync failed — {exc}"))
                continue

    def _token(self):
        """Accounts mints its own tokens. No need to call /api/token
        and /api/refresh as it is the issuer. On a 401,
        just mint a new access token for the service user accounts.
        """
        return str(AccessToken.for_user(self.service_user))

    def _get(self, url, client):
        """GET with a bearer token. Re-minting once on 401/403.
        A second 401/403 means the service account doesn't
        # have staff perissions and should raise.
        5xx/429 are retried by the retry session utility.
        """
        headers = {"Authorization": f"Bearer {self._token()}"}
        resp = self.session.get(url, headers=headers, timeout=30)
        if resp.status_code in (401, 403):
            # MuckRock returns a 401 on an expired token.
            # DocumentCloud returns a 403 when a token is expired.
            # we should try to remint once. If it still throws a 401/403,
            # it is a permissions issue and should raise instead.
            # This is what python-squarelet does.
            logger.info(
                "[stats sync] %s on %s, re-minting token and retrying",
                resp.status_code,
                client,
            )
            headers = {"Authorization": f"Bearer {self._token()}"}
            resp = self.session.get(url, headers=headers, timeout=30)
            if resp.status_code in (401, 403):
                raise CommandError(
                    f"{client}: {resp.status_code} after re-minting — is the service "
                    f"account staff on {client}?"
                )
        resp.raise_for_status()
        return resp.json()

    def _sync_endpoint(self, url, client, model, uuid_field):
        """Page a client's stats endpoint, merging each page as it arrives so
        the full result set is never held in memory. Returns
        (matched_count, unmatched_uuids)."""
        total = 0
        unmatched = []
        while url:
            data = self._get(url, client)
            rows = {row["uuid"]: row for row in data["results"]}
            matched, page_unmatched = self._merge_page(model, uuid_field, rows, client)
            total += matched
            unmatched.extend(page_unmatched)
            url = data.get("next")
        if unmatched:
            logger.warning(
                "[stats sync] %s %s: %d fetched rows had no matching Accounts "
                "entity (likely pre-Accounts accounts): %s",
                client,
                model.__name__,
                len(unmatched),
                unmatched[:20],
            )
        return total, unmatched

    def _merge_page(self, model, uuid_field, rows, client):
        """Merge one page of stats in. Returns
        (matched_count, unmatched_uuids). A fetched UUID with no corresponding
        Accounts entity is skipped and returned as unmatched."""
        if not rows:
            return 0, []
        batch = []
        matched_uuids = set()
        qs = model.objects.filter(**{f"{uuid_field}__in": list(rows)})
        for entity in qs:
            key = str(getattr(entity, uuid_field))
            data = rows.get(key)
            if data is None:
                continue
            matched_uuids.add(key)
            stats = entity.client_stats or {}
            stats[client] = data
            entity.client_stats = stats
            batch.append(entity)
        if batch:
            model.objects.bulk_update(batch, ["client_stats"])
        unmatched = [uuid for uuid in rows if uuid not in matched_uuids]
        return len(batch), unmatched
