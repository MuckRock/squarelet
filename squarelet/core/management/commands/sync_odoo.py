# Django
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand

# Standard Library
import logging
from datetime import date, datetime, timezone
from io import StringIO

# Third Party
import requests

# Squarelet
from squarelet.core.utils import requests_retry_session
from squarelet.organizations.models.organization import Organization
from squarelet.organizations.models.payment import Plan
from squarelet.organizations.plan_mapping import LEGACY_PLAN_MAP

logger = logging.getLogger(__name__)

SKIP_SLUGS = {
    "sunlight-search",
    "muckrock",
    "bu-spark",
    "muckrock-alumni",
    "muckrock-proxies",
    "sunlight-research-desk",
}

# Default page size for paginated search_read calls
_PAGE_SIZE = 200

# x_plan_tier slug -> id, and the reverse, loaded once per run
_TIER_ID_CACHE = {}
_TIER_SLUG_BY_ID = {}

LINE_FIELDS = ["x_interval", "x_rate", "x_code", "x_renews_on", "x_cancelling"]

# Client-stats fields synced to Odoo
STAT_INT_FIELDS = {
    "x_studio_mr_total_requests",
    "x_studio_mr_recent_requests",
    "x_studio_dc_total_documents",
    "x_studio_dc_recent_uploads",
}
STAT_DATETIME_FIELDS = {
    "x_studio_mr_last_login",
    "x_studio_mr_last_request",
    "x_studio_dc_last_login",
    "x_studio_dc_last_upload",
    "x_studio_dc_last_ai_credit",
}
STAT_FIELDS = sorted(STAT_INT_FIELDS | STAT_DATETIME_FIELDS)


def _headers():
    return {
        "Authorization": f"bearer {settings.ODOO_API_KEY}",
        "Content-Type": "application/json",
    }


_session = requests_retry_session()


def _odoo_request(endpoint, payload):
    """POST to an Odoo JSON-2 endpoint via the retry session.
    Uses requests_retry_session which will retry on intermittent issues.
    Returns parsed JSON on success, or raises on failures that are ongoing.
    The exception propagates to handle, which catches it,
    sets failed = True, and emails the failure report."""
    url = f"{settings.ODOO_URL}/json/2/{endpoint}"
    try:
        resp = _session.post(
            url,
            headers=_headers(),
            json=payload,
            timeout=settings.ODOO_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        logger.error("Odoo request failed for %s: %s", endpoint, exc)
        raise


def odoo_search(model, domain, fields, limit=1, offset=0):
    result = _odoo_request(
        f"{model}/search_read",
        {"domain": domain, "fields": fields, "limit": limit, "offset": offset},
    )
    return result if result is not None else []


def odoo_search_all(model, domain, fields, page_size=_PAGE_SIZE):
    """search_read every matching row, paging so nothing is capped.
    Stops when a batch comes back smaller than page_size."""
    results = []
    offset = 0
    while True:
        batch = odoo_search(model, domain, fields, limit=page_size, offset=offset)
        results.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return results


def odoo_create(model, vals):
    return _odoo_request(f"{model}/create", {"vals_list": [vals]})


def odoo_write(model, ids, vals):
    return _odoo_request(f"{model}/write", {"ids": ids, "vals": vals})


def odoo_unlink(model, ids):
    return _odoo_request(f"{model}/unlink", {"ids": ids})


def log_org_note(odoo_id, body, dry_run=False):
    """Post an internal note to an org's Odoo chatter (mail.thread log)."""
    if dry_run:
        logger.info("[DRY RUN] Would log note on Odoo ID %s: %s", odoo_id, body)
        return
    _odoo_request(
        "res.partner/message_post",
        {
            "ids": [odoo_id],
            "body": body,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_note",
        },
    )
    logger.info("Logged note on Odoo ID %s", odoo_id)


def _parse_dt(value):
    """ISO 8601 client-stats timestamp -> naive-UTC string Odoo accepts
    ('YYYY-MM-DD HH:MM:SS'), or False when missing. Handles both the
    '+/-HH:MM' offsets (MuckRock) and the 'Z' suffix (DocumentCloud)."""
    if not value:
        return False
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _build_stats_vals(stats):
    """Map the Accounts client-stats JSON to Odoo stat fields: last-activity
    dates, totals, and recent-activity counts. The AI-credit and request
    balance sub-objects are intentionally skipped, and days-since is computed
    in Odoo, not synced."""
    stats = stats or {}
    mr = stats.get("muckrock") or {}
    dc = stats.get("documentcloud") or {}
    return {
        "x_studio_mr_last_login": _parse_dt(mr.get("last_login_at")),
        "x_studio_mr_last_request": _parse_dt(mr.get("last_request_at")),
        "x_studio_mr_total_requests": mr.get("total_requests") or 0,
        "x_studio_mr_recent_requests": mr.get("recent_request_count") or 0,
        "x_studio_dc_last_login": _parse_dt(dc.get("last_login_at")),
        "x_studio_dc_last_upload": _parse_dt(dc.get("last_upload_at")),
        "x_studio_dc_last_ai_credit": _parse_dt(dc.get("last_ai_credit_at")),
        "x_studio_dc_total_documents": dc.get("total_documents") or 0,
        "x_studio_dc_recent_uploads": dc.get("recent_upload_count") or 0,
    }


def _normalize_stat(field, value):
    """Normalize a value read back from Odoo so it compares cleanly against
    _build_stats_vals output (empty int -> 0, empty datetime -> False)."""
    if field in STAT_INT_FIELDS:
        return value or 0
    return value or False


# --- Plan lines -------------------------------------------------------------


def _m2o_id(value):
    """Odoo many2one value ([id, name], id, or False) -> id or False."""
    if isinstance(value, (list, tuple)):
        return value[0]
    return value or False


def _m2o_name(value):
    """Odoo many2one value -> display name, or '' when absent."""
    if isinstance(value, (list, tuple)):
        return value[1]
    return ""


def _load_tiers():
    """Load every Odoo tier so lines compare by slug, even for tiers not yet created."""
    for tier in odoo_search_all("x_plan_tier", [], ["id", "x_slug"]):
        _TIER_ID_CACHE[tier["x_slug"]] = tier["id"]
        _TIER_SLUG_BY_ID[tier["id"]] = tier["x_slug"]


def _resolve_tier_id(tier_slug, fallback_name):
    """Odoo x_plan_tier id for a canonical slug, creating the tier if missing."""
    if tier_slug in _TIER_ID_CACHE:
        return _TIER_ID_CACHE[tier_slug]
    plan = Plan.objects.filter(slug=tier_slug).first()
    name = plan.name if plan else fallback_name
    result = odoo_create("x_plan_tier", {"x_name": name, "x_slug": tier_slug})
    if not result:
        logger.error("Failed to create Odoo tier: %s", tier_slug)
        return None
    _TIER_ID_CACHE[tier_slug] = result[0]
    _TIER_SLUG_BY_ID[result[0]] = tier_slug
    logger.info("Created Odoo tier: %s (%s)", name, tier_slug)
    return result[0]


def _tier_for(plan, is_billing):
    """(tier slug, interval, rate) for a legacy line with no PlanPrice yet."""
    target = LEGACY_PLAN_MAP.get((plan.slug, is_billing))
    if target is not None:
        return target[0], target[1], target[2]
    slug = plan.slug
    if plan.free:
        rate = "comped"
    elif "nonprofit" in slug:
        rate = "nonprofit"
    else:
        rate = "standard"
    tier_slug = slug.replace("sunlight-nonprofit-", "sunlight-")
    if tier_slug.endswith("-annual"):
        tier_slug = tier_slug[: -len("-annual")]
    interval = "annual" if plan.annual else "monthly"
    return tier_slug, interval, rate


def _item_spec(item):
    """Desired plan-line fields for one SubscriptionItem, with no source."""
    subscription = item.subscription
    if item.plan_price_id:
        price = item.plan_price
        tier_slug = price.plan.slug
        tier_name = price.plan.name
        interval = price.interval
        rate = price.label
        code = price.code
    else:
        tier_slug, interval, rate = _tier_for(
            item.plan, bool(subscription.subscription_id)
        )
        tier_name = item.plan.name.split(" (")[0]
        code = ""
    renews_on = item.ends_on or subscription.next_date
    return {
        "tier_slug": tier_slug,
        "tier_name": tier_name,
        "x_source_id": False,
        "x_interval": interval,
        "x_rate": rate,
        "x_code": code,
        "x_renews_on": renews_on.isoformat() if renews_on else False,
        # One-off subscriptions are flagged cancelled at purchase
        # only renewing ones can be cancelling
        "x_cancelling": subscription.cancelled and subscription.kind != "one_off",
        "wix": item.plan.wix,
    }


def _org_item_specs(org):
    """Plan-line specs for every line on the org's own subscriptions
    from the prefetch."""
    specs = []
    for subscription in org.subscriptions.all():
        for item in subscription.items.all():
            specs.append(_item_spec(item))
    return specs


def _member_copies(org_lines, odoo_org_id):
    """Org lines as a member carries them: the org's own lines sourced from the org."""
    copies = []
    for spec in org_lines:
        copy = dict(spec)
        if copy["x_source_id"] is False:
            copy["x_source_id"] = odoo_org_id
        copies.append(copy)
    return copies


def _spec_key(spec):
    return (spec["tier_slug"], spec["x_source_id"])


def _line_key(line):
    return (
        _TIER_SLUG_BY_ID.get(_m2o_id(line["x_tier_id"])),
        _m2o_id(line["x_source_id"]),
    )


def _normalize_line_field(field, value):
    """Normalize a plan-line value read from Odoo to compare against a spec."""
    if field == "x_code":
        return value or ""
    if field == "x_cancelling":
        return bool(value)
    return value or False


def _write_plan_line(partner_id, label, spec, line, dry_run):
    """Create a missing plan line, or update one whose fields differ."""
    vals = {}
    for field in LINE_FIELDS:
        if field == "x_renews_on" and spec[field] is False:
            continue  # Accounts has no date (comped or free); keep the one set in Odoo
        vals[field] = spec[field]
    if line is None:
        if dry_run:
            logger.info(
                "[DRY RUN] Would add plan line %s for %s: %s",
                spec["tier_slug"],
                label,
                vals,
            )
            return
        tier_id = _resolve_tier_id(spec["tier_slug"], spec["tier_name"])
        if tier_id is None:
            return
        vals["x_partner_id"] = partner_id
        vals["x_tier_id"] = tier_id
        vals["x_source_id"] = spec["x_source_id"]
        odoo_create("x_plan_line", vals)
        logger.info("Added plan line %s for %s", spec["tier_slug"], label)
        return
    changes = {}
    for field in vals:
        current = _normalize_line_field(field, line.get(field))
        if current != vals[field]:
            changes[field] = (current, vals[field])
    if not changes:
        return
    if dry_run:
        logger.info(
            "[DRY RUN] Would update plan line %s for %s: %s",
            spec["tier_slug"],
            label,
            changes,
        )
        return
    odoo_write("x_plan_line", [line["id"]], vals)
    logger.info("Updated plan line %s for %s: %s", spec["tier_slug"], label, changes)


def _sync_plan_lines(partner_id, label, specs, dry_run, managed_sources=None):
    """Make a partner's plan lines match specs, touching only lines from managed_sources
    (None manages all); returns tier names of removed lines."""
    current = odoo_search_all(
        "x_plan_line",
        [["x_partner_id", "=", partner_id]],
        ["id", "x_tier_id", "x_source_id"] + LINE_FIELDS,
    )
    current_by_key = {}
    for line in current:
        if (
            managed_sources is not None
            and _m2o_id(line["x_source_id"]) not in managed_sources
        ):
            continue  # owned by another pass, e.g. a personal plan or another org
        current_by_key[_line_key(line)] = line
    desired_by_key = {}
    for spec in specs:
        desired_by_key[_spec_key(spec)] = spec

    for key, spec in desired_by_key.items():
        _write_plan_line(partner_id, label, spec, current_by_key.get(key), dry_run)

    stale_ids = []
    stale_names = []
    for key, line in current_by_key.items():
        if key not in desired_by_key:
            stale_ids.append(line["id"])
            stale_names.append(_m2o_name(line["x_tier_id"]) or str(key[0]))
    if not stale_ids:
        return []
    if dry_run:
        logger.info("[DRY RUN] Would remove plan lines for %s: %s", label, stale_names)
    else:
        odoo_unlink("x_plan_line", stale_ids)
        logger.info("Removed plan lines for %s: %s", label, stale_names)
    return stale_names


def _line_names(partner_id):
    """Tier names of a partner's current plan lines, for notes."""
    names = []
    for line in odoo_search_all(
        "x_plan_line", [["x_partner_id", "=", partner_id]], ["x_tier_id"]
    ):
        names.append(_m2o_name(line["x_tier_id"]))
    return names


def _remove_member_lines(member_id, keys):
    """Delete a member's plan lines that were copied from their org."""
    current = odoo_search_all(
        "x_plan_line",
        [["x_partner_id", "=", member_id]],
        ["id", "x_tier_id", "x_source_id"],
    )
    ids = []
    for line in current:
        if _line_key(line) in keys:
            ids.append(line["id"])
    if ids:
        odoo_unlink("x_plan_line", ids)
    return len(ids)


# --- Orgs -------------------------------------------------------------------


def _build_org_vals(org, sunlight_status, member_tag_ids):
    """Build the vals dict for a res.partner org record."""
    # Read the urls from the prefetch
    urls = [u.url for u in org.urls.all()]
    vals = {
        "name": org.name,
        "x_studio_slug": org.slug,
        "x_studio_muckrock_accounts_id": org.id,
        "x_studio_muckrock_accounts_uuid": str(org.uuid),
        "x_studio_muckrock_accounts": True,
        "city": org.city or "",
        "website": ", ".join(urls),
        "x_studio_verified_journalist": org.verified_journalist,
        "is_company": True,
        "company_type": "company",
    }
    if sunlight_status is not None:
        vals["x_studio_sunlight_status"] = sunlight_status
    if member_tag_ids:
        # (4, id) links an existing tag without disturbing other tags
        vals["category_id"] = [(4, tag_id) for tag_id in member_tag_ids]
    if org.about:
        vals["x_studio_about"] = org.about
    vals.update(_build_stats_vals(org.client_stats))
    return vals


def _sunlight_status(own_specs):
    """'Confirmed' when the org's own lines include a Sunlight (wix) plan, else None."""
    for spec in own_specs:
        if spec["wix"]:
            return "Confirmed"
    return None


def _reconcile_category_id(
    current, current_normalized, vals_normalized, member_tag_ids
):
    """Fold the category_id (member-tag) field into the normalized dicts so the
    diff only fires when a desired tag is actually missing in Odoo. Mutates
    current_normalized / vals_normalized in place."""
    if not member_tag_ids:
        current_normalized.pop("category_id", None)
        vals_normalized.pop("category_id", None)
        return
    current_tags = set(current.get("category_id") or [])
    missing_tags = [t for t in member_tag_ids if t not in current_tags]
    if missing_tags:
        vals_normalized["category_id"] = f"add_tags:{missing_tags}"
        current_normalized["category_id"] = f"missing_tags:{missing_tags}"
    else:
        current_normalized.pop("category_id", None)
        vals_normalized.pop("category_id", None)


def _diff_and_update_org(
    org, odoo_id, vals, sunlight_status, member_tag_ids, dry_run
):  # pylint:disable=too-many-positional-arguments
    """Compare current Odoo state to desired vals and write if changed."""
    current = odoo_search(
        "res.partner",
        [["id", "=", odoo_id]],
        [
            "name",
            "x_studio_slug",
            "x_studio_muckrock_accounts_id",
            "x_studio_muckrock_accounts_uuid",
            "x_studio_muckrock_accounts",
            "city",
            "website",
            "x_studio_verified_journalist",
            "x_studio_sunlight_status",
            "is_company",
            "company_type",
            "x_studio_about",
            "category_id",
        ]
        + STAT_FIELDS,
    )[0]

    current_normalized = {k: v for k, v in current.items() if k != "id"}
    current_normalized["category_id"] = sorted(current.get("category_id") or [])
    for f in STAT_FIELDS:
        current_normalized[f] = _normalize_stat(f, current.get(f))
    for k in current_normalized:
        if current_normalized[k] is False and k in vals and vals[k] == "":
            current_normalized[k] = ""

    vals_normalized = {k: v for k, v in vals.items() if k != "category_id"}
    if sunlight_status is None:
        current_normalized.pop("x_studio_sunlight_status", None)

    _reconcile_category_id(current, current_normalized, vals_normalized, member_tag_ids)

    diffs = {
        k: (current_normalized.get(k), vals_normalized[k])
        for k in vals_normalized
        if current_normalized.get(k) != vals_normalized[k]
    }
    if not diffs:
        logger.info("No changes for org: %s", org.name)
        return
    if dry_run:
        logger.info(
            "[DRY RUN] Would update org: %s (Odoo ID %s) — changes: %s",
            org.name,
            odoo_id,
            diffs,
        )
    else:
        odoo_write("res.partner", [odoo_id], vals)
        logger.info("Updated org: %s", org.name)


def get_or_create_org(org, sunlight_status, dry_run=False, member_tag_ids=None):
    """Find or create the org's Odoo partner, updating it if changed; returns its id."""
    if org.slug in SKIP_SLUGS:
        logger.info("Skipping org: %s (%s)", org.name, org.slug)
        return None

    results = odoo_search(
        "res.partner",
        [["x_studio_slug", "=", org.slug], ["is_company", "=", True]],
        ["id"],
    )
    vals = _build_org_vals(org, sunlight_status, member_tag_ids)

    if results:
        odoo_id = results[0]["id"]
        _diff_and_update_org(
            org, odoo_id, vals, sunlight_status, member_tag_ids, dry_run
        )
        return odoo_id
    if dry_run:
        logger.info("[DRY RUN] Would create org: %s (slug=%s)", org.name, org.slug)
        return None
    result = odoo_create("res.partner", vals)
    if not result:
        logger.error("Failed to create org in Odoo: %s", org.name)
        return None
    logger.info("Created org: %s", org.name)
    return result[0]


# --- Members ----------------------------------------------------------------


def _find_member(user):
    """Find an existing Odoo contact for a Accounts user by account uuid
    (globally unique), falling back to email ONLY for contacts not yet linked
    to any account. Returns (odoo_id or None, matched_via_secondary).

    The email fallback is filtered to contacts with an empty
    x_studio_muckrock_accounts_uuid so that a contact already claimed by one
    account can't be re-matched (and overwritten) by a different account that
    happens to share an email — e.g. one person with two accounts from Accounts
    under different emails. In that case the second account misses both the
    uuid and the (uuid-filtered) email match and correctly creates its own
    contact. Deduping those underlying accounts is handled upstream, not here."""
    uuid_str = str(user.uuid)

    # 1. Exact account match by uuid — unambiguous, one account = one contact
    results = odoo_search(
        "res.partner",
        [
            ["x_studio_muckrock_accounts_uuid", "=", uuid_str],
            ["is_company", "=", False],
        ],
        ["id"],
    )
    if results:
        return results[0]["id"], False

    # 2. Fall back to email (primary, then secondary), but only for contacts
    #    not yet linked to an account (no uuid) — first sync of a pre-existing
    #    Odoo contact.
    results = odoo_search(
        "res.partner",
        [
            ["email", "=", user.email],
            ["x_studio_muckrock_accounts_uuid", "=", False],
            ["is_company", "=", False],
        ],
        ["id"],
    )
    if results:
        return results[0]["id"], False
    results = odoo_search(
        "res.partner",
        [
            ["x_studio_secondary_email", "=", user.email],
            ["x_studio_muckrock_accounts_uuid", "=", False],
            ["is_company", "=", False],
        ],
        ["id"],
    )
    if results:
        return results[0]["id"], True
    return None, False


def _member_vals(user, odoo_org_id, matched_via_secondary):
    """Build the base res.partner vals for a member contact."""
    vals = {
        "name": user.name,
        "email": user.email,
        "parent_id": odoo_org_id,
        "is_company": False,
        "company_type": "person",
        "x_studio_muckrock_accounts": True,
        "x_studio_muckrock_accounts_id": user.id,
        "x_studio_muckrock_accounts_uuid": str(user.uuid),
    }
    if matched_via_secondary:
        del vals["email"]
    vals.update(_build_stats_vals(user.client_stats))
    return vals


def sync_member(user, org_name, odoo_org_id, dry_run=False):
    """Create or update a member contact
    returns its Odoo id, or None in dry-run create.
    """
    odoo_id, matched_via_secondary = _find_member(user)
    vals = _member_vals(user, odoo_org_id, matched_via_secondary)

    if odoo_id is None:
        if dry_run:
            logger.info(
                "[DRY RUN] Would create member: %s under org: %s", user.email, org_name
            )
            return None
        result = odoo_create("res.partner", vals)
        logger.info("Created member: %s (%s)", user.email, org_name)
        return result[0] if result else None

    _update_member(user, org_name, odoo_id, vals, dry_run)
    return odoo_id


def _update_member(user, org_name, odoo_id, vals, dry_run):
    """Diff an existing member against desired vals and write if changed."""
    current = odoo_search(
        "res.partner",
        [["id", "=", odoo_id]],
        [
            "name",
            "email",
            "parent_id",
            "is_company",
            "company_type",
            "x_studio_muckrock_accounts",
            "x_studio_muckrock_accounts_id",
            "x_studio_muckrock_accounts_uuid",
        ]
        + STAT_FIELDS,
    )[0]
    current_parent = current.get("parent_id")
    normalized = {
        "name": current["name"],
        "email": current["email"],
        "parent_id": current_parent[0] if current_parent else None,
        "is_company": current["is_company"],
        "company_type": current["company_type"],
        "x_studio_muckrock_accounts": current["x_studio_muckrock_accounts"],
        "x_studio_muckrock_accounts_id": current["x_studio_muckrock_accounts_id"],
        "x_studio_muckrock_accounts_uuid": current["x_studio_muckrock_accounts_uuid"],
    }
    for f in STAT_FIELDS:
        normalized[f] = _normalize_stat(f, current.get(f))
    diffs = {k: (normalized[k], v) for k, v in vals.items() if normalized.get(k) != v}

    if "parent_id" in diffs and normalized.get("parent_id") is not None:
        logger.info(
            "Note: %s already linked to parent ID %s, skipping reassignment to %s",
            user.email,
            normalized["parent_id"],
            vals["parent_id"],
        )
        del diffs["parent_id"]
        del vals["parent_id"]

    if not diffs:
        logger.info("No changes for member: %s (%s)", user.email, org_name)
        return

    if dry_run:
        logger.info(
            "[DRY RUN] Would update member: %s (%s) — changes: %s",
            user.email,
            org_name,
            diffs,
        )
    else:
        odoo_write("res.partner", [odoo_id], vals)
        logger.info("Updated member: %s (%s)", user.email, org_name)


def _unlink_departed_member(member, org, member_line_keys, dry_run):
    """Unlink a departed member and delete the plan lines they carried from the org."""
    email = (member.get("email") or "").lower()
    if dry_run:
        logger.info(
            "[DRY RUN] Would unlink departed member: %s (org: %s) and remove "
            "their org plan lines",
            email,
            org.name,
        )
        return
    odoo_write("res.partner", [member["id"]], {"parent_id": False})
    removed = _remove_member_lines(member["id"], member_line_keys)
    logger.info(
        "Unlinked departed member: %s (org: %s, removed %d plan lines)",
        email,
        org.name,
        removed,
    )


def _flag_departed_member(member, org, dry_run):
    """Flag a departed member with today's date (soft departure)."""
    email = (member.get("email") or "").lower()
    if dry_run:
        logger.info(
            "[DRY RUN] Would flag departed member: %s (org: %s)", email, org.name
        )
        return
    today = date.today().isoformat()
    odoo_write("res.partner", [member["id"]], {"x_studio_org_departed_date": today})
    logger.info(
        "Flagged departed member: %s (org: %s, departed: %s)", email, org.name, today
    )


def _is_departed(member, current_emails):
    """True if this Odoo member is no longer in the org
    and is eligible for departure handling."""
    primary = (member.get("email") or "").lower()
    secondary = (member.get("x_studio_secondary_email") or "").lower()
    if not primary:
        return False
    if primary in current_emails or secondary in current_emails:
        return False
    if not member.get("x_studio_muckrock_accounts", False):
        logger.info("Member in Odoo but never on Accounts, skipping: %s", primary)
        return False
    return True


def remove_departed_members(
    org, odoo_org_id, member_line_keys, remove=False, dry_run=False
):
    # Read from the users prefetch
    current_emails = {u.email.lower() for u in org.users.all()}

    odoo_members = odoo_search_all(
        "res.partner",
        [["parent_id", "=", odoo_org_id], ["is_company", "=", False]],
        [
            "id",
            "email",
            "x_studio_muckrock_accounts",
            "x_studio_org_departed_date",
            "x_studio_secondary_email",
        ],
    )

    for member in odoo_members:
        if not _is_departed(member, current_emails):
            continue
        if remove:
            _unlink_departed_member(member, org, member_line_keys, dry_run)
        elif not member.get("x_studio_org_departed_date", False):
            _flag_departed_member(member, org, dry_run)


# --- Individuals ------------------------------------------------------------


def _sync_individual(org, dry_run):
    """Sync an individual subscriber's own plan lines onto their contact"""
    user = org.user
    specs = _org_item_specs(org)
    odoo_id, matched_via_secondary = _find_member(user)
    vals = _member_vals(user, None, matched_via_secondary)
    del vals["parent_id"]  # leave any org link the contact already has alone

    if odoo_id is None:
        if dry_run:
            tiers = []
            for spec in specs:
                tiers.append(spec["tier_slug"])
            logger.info(
                "[DRY RUN] Would create individual: %s (plans: %s)", user.email, tiers
            )
            return None
        result = odoo_create("res.partner", vals)
        if not result:
            logger.error("Failed to create individual in Odoo: %s", user.email)
            return None
        odoo_id = result[0]
        logger.info("Created individual: %s", user.email)
    else:
        _update_member(user, "individual", odoo_id, vals, dry_run)

    _sync_plan_lines(odoo_id, user.email, specs, dry_run, managed_sources={False})
    return odoo_id


def _sweep_lapsed_personal_lines(active_contact_ids, dry_run=False):
    """Remove personal (unsourced) lines from contacts
    whose individual subscription ended."""
    stale = odoo_search_all(
        "x_plan_line",
        [
            ["x_source_id", "=", False],
            ["x_partner_id.is_company", "=", False],
            ["x_partner_id", "not in", sorted(active_contact_ids)],
        ],
        ["id", "x_partner_id", "x_tier_id"],
    )
    if not stale:
        return
    ids = []
    for line in stale:
        ids.append(line["id"])
        logger.info(
            "%sRemoving lapsed personal plan line %s from %s",
            "[DRY RUN] " if dry_run else "",
            _m2o_name(line["x_tier_id"]),
            _m2o_name(line["x_partner_id"]),
        )
    if not dry_run:
        odoo_unlink("x_plan_line", ids)


def _build_individual_queryset():
    """Return every individual org with a subscription line."""
    return (
        Organization.objects.filter(individual=True, subscriptions__items__isnull=False)
        .distinct()
        .prefetch_related(
            "subscriptions__items__plan",
            "subscriptions__items__plan_price__plan",
        )
    )


# --- Sweeps -----------------------------------------------------------------


def cancel_org(odoo_id, name, dry_run=False):
    """Cancel a single Confirmed org, noting which plan lines it still carries.

    This is a full-lapse audit note: such an org fell out of the sync set
    entirely, so the per-org path never ran for it — this is the only place
    the lapse is recorded. Lines are left in place, like the status sweep."""
    if dry_run:
        logger.info("[DRY RUN] Would cancel lapsed org: %s (Odoo ID %s)", name, odoo_id)
    else:
        odoo_write(
            "res.partner",
            [odoo_id],
            {"x_studio_sunlight_status": "Cancelled"},
        )
        logger.info("Cancelled lapsed org: %s", name)
    names = _line_names(odoo_id)
    if names:
        body = f"Marked Cancelled by Accounts sync — lost plan(s): {', '.join(names)}."
    else:
        body = "Marked Cancelled by Accounts sync — no active Sunlight plan."
    log_org_note(odoo_id, body, dry_run=dry_run)


def _sweep_lapsed_orgs(active_slugs, dry_run=False, only_slug=None):
    """Find Confirmed Odoo orgs no longer active in Accounts, cancel each."""
    logger.info(
        "Checking %d active Accounts slugs against Odoo confirmed orgs",
        len(active_slugs),
    )
    domain = [
        ["x_studio_sunlight_status", "=", "Confirmed"],
        ["is_company", "=", True],
        ["x_studio_slug", "not in", list(active_slugs | SKIP_SLUGS)],
    ]
    if only_slug is not None:
        domain.append(["x_studio_slug", "=", only_slug])

    candidates = odoo_search_all("res.partner", domain, ["id", "name"])

    logger.info(
        "Found %d confirmed orgs in Odoo with no active plan in Accounts"
        " — these would be cancelled",
        len(candidates),
    )
    for org in candidates:
        cancel_org(org["id"], org["name"], dry_run=dry_run)


class CollaborativeConfig:
    """Holds resolved runtime data for a collaborative org."""

    def __init__(
        self, slug, tag_id, member_slugs, odoo_id, line_specs
    ):
        self.slug = slug
        self.tag_id = tag_id
        self.member_slugs = member_slugs
        self.odoo_id = odoo_id
        self.line_specs = line_specs


def remove_collaborative_tag(tagged, config, dry_run=False):
    """Remove a collaborative tag and its sourced
    plan lines from an org and its contacts.
    """
    if dry_run:
        logger.info(
            "[DRY RUN] Would remove %s Member tag and its plan lines from: %s "
            "(Odoo ID %s)",
            config.slug,
            tagged["name"],
            tagged["id"],
        )
        return
    odoo_write("res.partner", [tagged["id"]], {"category_id": [(3, config.tag_id)]})
    removed_names = []
    if config.odoo_id:
        sourced = odoo_search_all(
            "x_plan_line",
            [
                ["x_source_id", "=", config.odoo_id],
                ["x_partner_id", "child_of", tagged["id"]],
            ],
            ["id", "x_tier_id", "x_partner_id"],
        )
        sourced_ids = []
        for line in sourced:
            sourced_ids.append(line["id"])
            if _m2o_id(line["x_partner_id"]) == tagged["id"]:
                removed_names.append(_m2o_name(line["x_tier_id"]))
        if sourced_ids:
            odoo_unlink("x_plan_line", sourced_ids)
    logger.info("Removed %s Member tag from: %s", config.slug, tagged["name"])
    if removed_names:
        log_org_note(
            tagged["id"],
            f"Plan(s) removed — no longer a {config.slug} member: "
            f"{', '.join(removed_names)}",
            dry_run=dry_run,
        )


def _sweep_stale_collaborative_tags(config, dry_run=False, only_slug=None):
    """Find orgs carrying a collaborative tag but no longer members, untag each."""
    domain = [["category_id", "in", [config.tag_id]], ["is_company", "=", True]]
    if only_slug is not None:
        domain.append(["x_studio_slug", "=", only_slug])
    tagged_orgs = odoo_search_all(
        "res.partner",
        domain,
        ["id", "name", "x_studio_slug"],
    )
    for tagged in tagged_orgs:
        if (
            tagged["x_studio_slug"]
            and tagged["x_studio_slug"] not in config.member_slugs
        ):
            remove_collaborative_tag(tagged, config, dry_run=dry_run)


def _collaborative_renewals(odoo_id):
    """Renewal date per tier on a collaborative's own Odoo lines, where staff set it."""
    renews_by_tier = {}
    own_lines = odoo_search_all(
        "x_plan_line",
        [["x_partner_id", "=", odoo_id], ["x_source_id", "=", False]],
        ["x_tier_id", "x_renews_on"],
    )
    for line in own_lines:
        tier_slug = _TIER_SLUG_BY_ID.get(_m2o_id(line["x_tier_id"]))
        if tier_slug and line["x_renews_on"]:
            renews_by_tier[tier_slug] = line["x_renews_on"]
    return renews_by_tier


def _load_collaborative_data():
    """Load CollaborativeConfig for every collective-enabled org.
    Which orgs are collaboratives comes from the DB (collective_enabled);
    the Odoo tag id comes from settings.COLLABORATIVE_TAGS (slug -> tag id).
    A collective-enabled org with no configured tag is skipped with a warning.
    Inherited lines with no Accounts renewal date take the one on the
    collaborative's own Odoo line, so it is set in one place."""
    collaborative_data = {}
    collab_orgs = Organization.objects.filter(
        collective_enabled=True,
        individual=False,
    ).prefetch_related(
        "subscriptions__items__plan",
        "subscriptions__items__plan_price__plan",
        "members",
    )
    for collab_org in collab_orgs:
        tag_id = settings.COLLABORATIVE_TAGS.get(collab_org.slug)
        if tag_id is None:
            logger.warning(
                "Collective-enabled org has no Odoo tag configured, "
                "skipping tagging: %s (%s)",
                collab_org.name,
                collab_org.slug,
            )
            continue
        tag_id = int(tag_id)
        member_slugs = set()
        # Use the members prefetch
        for member in collab_org.members.all():
            member_slugs.add(member.slug)

        res = odoo_search(
            "res.partner",
            [["x_studio_slug", "=", collab_org.slug], ["is_company", "=", True]],
            ["id"],
        )
        odoo_id = res[0]["id"] if res else None
        line_specs = []
        if odoo_id is None:
            logger.warning(
                "Collaborative not in Odoo, no inherited lines: %s", collab_org.slug
            )
        else:
            renews_by_tier = _collaborative_renewals(odoo_id)
            for spec in _org_item_specs(collab_org):
                if not spec["wix"]:
                    continue
                spec["x_source_id"] = odoo_id
                spec["x_rate"] = False
                if spec["x_renews_on"] is False:
                    spec["x_renews_on"] = renews_by_tier.get(spec["tier_slug"], False)
                line_specs.append(spec)

        collaborative_data[collab_org.slug] = CollaborativeConfig(
            collab_org.slug, tag_id, member_slugs, odoo_id, line_specs
        )
    return collaborative_data


def _build_org_queryset(collaborative_data):
    """Return every group org with a subscription line, plus collaborative members."""
    subscribed_slugs = set(
        Organization.objects.filter(
            subscriptions__items__isnull=False,
            individual=False,
        )
        .values_list("slug", flat=True)
        .distinct()
    )
    all_collaborative_member_slugs = set()
    for config in collaborative_data.values():
        all_collaborative_member_slugs |= config.member_slugs
    all_slugs = (subscribed_slugs | all_collaborative_member_slugs) - SKIP_SLUGS
    return Organization.objects.filter(slug__in=all_slugs).prefetch_related(
        "subscriptions__items__plan",
        "subscriptions__items__plan_price__plan",
        "users",
        "urls",
    )


def _sync_org(org, collaborative_data, dry_run, remove_members):
    """Sync a single org and its members. Returns the org slug if processed."""
    if org.slug in SKIP_SLUGS:
        return None

    own_lines = _org_item_specs(org)
    desired_lines = list(own_lines)
    member_tag_ids = []
    collab_odoo_ids = set()
    labels = []
    for config in collaborative_data.values():
        if org.slug in config.member_slugs:
            member_tag_ids.append(config.tag_id)
            labels.append(config.slug)
            desired_lines.extend(config.line_specs)
            if config.odoo_id:
                collab_odoo_ids.add(config.odoo_id)

    label_str = "/".join(labels) + " member " if labels else ""
    logger.info("Syncing %sorg: %s", label_str, org.name)

    odoo_org_id = get_or_create_org(
        org,
        _sunlight_status(own_lines),
        dry_run=dry_run,
        member_tag_ids=member_tag_ids or None,
    )

    if odoo_org_id is None:
        logger.info("Skipping members for %s — org not yet in Odoo", org.name)
        return org.slug

    removed_lines = _sync_plan_lines(odoo_org_id, org.name, desired_lines, dry_run)
    if removed_lines:
        log_org_note(
            odoo_org_id,
            f"Plan line(s) removed by Accounts sync: {', '.join(removed_lines)}",
            dry_run=dry_run,
        )

    # Members carry all of their org's lines, sourced from the org or its collaborative
    member_lines = _member_copies(desired_lines, odoo_org_id)
    member_sources = {odoo_org_id} | collab_odoo_ids
    member_line_keys = set()
    for spec in member_lines:
        member_line_keys.add(_spec_key(spec))

    for user in org.users.all():
        member_id = sync_member(user, org.name, odoo_org_id, dry_run=dry_run)
        if member_id is not None:
            _sync_plan_lines(
                member_id,
                user.email,
                member_lines,
                dry_run,
                managed_sources=member_sources,
            )

    remove_departed_members(
        org,
        odoo_org_id,
        member_line_keys,
        remove=remove_members,
        dry_run=dry_run,
    )
    return org.slug


def _run_sync(dry_run, remove_members, slug):
    """Run the full sync pass: load tiers, sync orgs + members, individuals, then
    the lapsed-org, lapsed-personal-line and stale-tag sweeps."""
    if dry_run:
        logger.info("DRY RUN - no changes will be made")
    _load_tiers()
    collaborative_data = _load_collaborative_data()

    all_orgs = _build_org_queryset(collaborative_data)
    if slug:
        all_orgs = all_orgs.filter(slug=slug)
    active_slugs = set()
    for org in all_orgs:
        processed_slug = _sync_org(org, collaborative_data, dry_run, remove_members)
        if processed_slug:
            active_slugs.add(processed_slug)

    individuals = _build_individual_queryset()
    if slug:
        individuals = individuals.filter(slug=slug)
    active_contact_ids = set()
    for org in individuals:
        contact_id = _sync_individual(org, dry_run)
        if contact_id is not None:
            active_contact_ids.add(contact_id)

    _sweep_lapsed_orgs(active_slugs, dry_run=dry_run, only_slug=slug)
    if not slug:
        _sweep_lapsed_personal_lines(active_contact_ids, dry_run=dry_run)
    for config in collaborative_data.values():
        if config.member_slugs:
            _sweep_stale_collaborative_tags(config, dry_run=dry_run, only_slug=slug)
    logger.info("Sync complete")


def _send_sync_report(buffer, failed):
    """Email the buffered sync log as an attachment, tagging the subject
    OK/FAILED. Called from handle's finally so a report goes out on both
    success and unhandled failure."""
    today = date.today().isoformat()
    status = "FAILED" if failed else "OK"
    email = EmailMessage(
        subject=f"Odoo Sync Report ({status}) - {today}",
        body=(
            "Sync encountered an error — see attached log for the traceback."
            if failed
            else "See attached for full sync report."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[settings.ODOO_SYNC_REPORT_EMAIL],
    )
    email.attach(f"sync_report_{today}.txt", buffer.getvalue(), "text/plain")
    email.send()


class Command(BaseCommand):
    """Sync Accounts subscribers (group orgs, their members, and individuals) to Odoo"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without making changes",
        )
        parser.add_argument(
            "--remove-members",
            action="store_true",
            help="Unlink members from Odoo orgs if they are no longer in Accounts",
        )
        parser.add_argument(
            "--slug",
            type=str,
            help="Limit sync to a single org (or individual) by slug",
        )

    def handle(self, *args, **kwargs):
        if not settings.ODOO_SYNC_ENABLED:
            self.stdout.write("ODOO_SYNC_ENABLED is not set; skipping sync.")
            return
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        _prev_level = logger.level
        logger.setLevel(logging.INFO)
        failed = False
        try:
            _run_sync(kwargs["dry_run"], kwargs["remove_members"], kwargs.get("slug"))
        except Exception:
            failed = True
            logger.exception("Sync failed with an unhandled exception")
            raise
        finally:
            handler.flush()
            logger.removeHandler(handler)
            logger.setLevel(_prev_level)
            _send_sync_report(buffer, failed)
