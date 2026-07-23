# Django
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand

# Standard Library
import logging
from datetime import date
from io import StringIO

# Third Party
import requests

# Squarelet
from squarelet.core.utils import requests_retry_session
from squarelet.organizations.models.organization import Membership, Organization
from squarelet.organizations.models.payment import Plan

logger = logging.getLogger(__name__)

SKIP_SLUGS = {"sunlight-search"}

# Cache of x_plan name -> id
_PLAN_ID_CACHE = {}

# Default page size for paginated search_read calls
_PAGE_SIZE = 200


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


def _resolve_plan_id(name):
    """Resolve a Squarelet plan to its Odoo x_plan id by name match.
    Creation is handled up front by _ensure_all_plans, so this is
    lookup-only; a missing plan means it wasn't in Squarelet at ensure time."""
    if name in _PLAN_ID_CACHE:
        return _PLAN_ID_CACHE[name]
    res = odoo_search("x_plan", [["x_name", "=", name]], ["id"])
    pid = res[0]["id"] if res else None
    if pid is None:
        logger.warning("No Odoo plan match for Squarelet plan: %s", name)
    _PLAN_ID_CACHE[name] = pid
    return pid


def _build_plan_vals(plan):
    """Map a Squarelet Plan to the x_plan fields Odoo mirrors."""
    return {
        "x_name": plan.name,
        "x_studio_slug": plan.slug,
        "x_studio_base_price": plan.base_price,
        "x_studio_price_per_user": plan.price_per_user,
        "x_studio_annual": plan.annual,
    }


def _resolve_or_create_plan(plan, dry_run):
    """Return the Odoo x_plan id for a Squarelet plan, creating it if
    missing. Returns None if it can't be resolved (dry-run, or a failed
    create)."""
    res = odoo_search("x_plan", [["x_name", "=", plan.name]], ["id"])
    if res:
        return res[0]["id"]
    if dry_run:
        logger.info("[DRY RUN] Would create Odoo plan: %s", plan.name)
        return None
    result = odoo_create("x_plan", _build_plan_vals(plan))
    if not result:
        logger.error("Failed to create Odoo plan: %s", plan.name)
        return None
    logger.info("Created Odoo plan: %s (x_plan ID %s)", plan.name, result[0])
    return result[0]


def _ensure_all_plans(dry_run=False):
    """Create an Odoo x_plan with full pricing data for any Squarelet
    plan that lacks one. Runs before sync so every plan resolves to a
    real id and no plan silently drops out of an org's plan list."""
    for plan in Plan.objects.all():
        if plan.name not in _PLAN_ID_CACHE:
            _PLAN_ID_CACHE[plan.name] = _resolve_or_create_plan(plan, dry_run)


def _build_org_vals(org, odoo_plan_ids, sunlight_status, member_tag_ids):
    """Build the vals dict for a res.partner org record."""
    urls = list(org.urls.values_list("url", flat=True))
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
        # (6, 0, ids) tells Odoo to set this field to exactly these plan
        # ids, replacing whatever was linked before
        "x_studio_plan_1": [(6, 0, odoo_plan_ids)],
    }
    if sunlight_status is not None:
        vals["x_studio_sunlight_status"] = sunlight_status
    if member_tag_ids:
        # (4, id) links an existing tag without disturbing other tags
        vals["category_id"] = [(4, tag_id) for tag_id in member_tag_ids]
    if org.about:
        vals["x_studio_about"] = org.about
    return vals


def _compute_org_plans_and_status(org, inherited_plan_ids):
    """Return (odoo_plan_ids, sunlight_status) for an org."""
    plans = list(org.plans.values_list("name", "wix"))
    has_sunlight = any(wix for _, wix in plans)
    own_plan_ids = [
        pid for pid in (_resolve_plan_id(name) for name, _ in plans) if pid is not None
    ]
    if inherited_plan_ids is not None:
        odoo_plan_ids = sorted(set(own_plan_ids + inherited_plan_ids))
    else:
        odoo_plan_ids = sorted(set(own_plan_ids))
    sunlight_status = "Confirmed" if has_sunlight else None
    return odoo_plan_ids, sunlight_status


def _diff_and_update_org(
    org, odoo_id, vals, odoo_plan_ids, sunlight_status, member_tag_ids, dry_run
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
            "x_studio_plan_1",
            "is_company",
            "company_type",
            "x_studio_about",
            "category_id",
        ],
    )[0]
    current_normalized = {k: v for k, v in current.items() if k != "id"}
    current_normalized["x_studio_plan_1"] = sorted(current.get("x_studio_plan_1") or [])
    current_normalized["category_id"] = sorted(current.get("category_id") or [])
    for k in current_normalized:
        if current_normalized[k] is False and k in vals and vals[k] == "":
            current_normalized[k] = ""

    vals_normalized = {
        k: v for k, v in vals.items() if k not in ("x_studio_plan_1", "category_id")
    }
    if sunlight_status is None:
        current_normalized.pop("x_studio_sunlight_status", None)
    vals_normalized["x_studio_plan_1"] = sorted(odoo_plan_ids)

    if member_tag_ids:
        current_tags = set(current.get("category_id") or [])
        missing_tags = [t for t in member_tag_ids if t not in current_tags]
        if missing_tags:
            vals_normalized["category_id"] = f"add_tags:{missing_tags}"
            current_normalized["category_id"] = f"missing_tags:{missing_tags}"
        else:
            current_normalized.pop("category_id", None)
            vals_normalized.pop("category_id", None)
    else:
        current_normalized.pop("category_id", None)
        vals_normalized.pop("category_id", None)

    diffs = {
        k: (current_normalized.get(k), vals_normalized[k])
        for k in vals_normalized
        if current_normalized.get(k) != vals_normalized[k]
    }
    if diffs:
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
    else:
        logger.info("No changes for org: %s", org.name)


def get_or_create_org(org, dry_run=False, member_tag_ids=None, inherited_plan_ids=None):
    if org.slug in SKIP_SLUGS:
        logger.info("Skipping org: %s (%s)", org.name, org.slug)
        return None, []

    results = odoo_search(
        "res.partner",
        [["x_studio_slug", "=", org.slug], ["is_company", "=", True]],
        ["id", "x_studio_plan_1", "x_studio_sunlight_status"],
    )

    odoo_plan_ids, sunlight_status = _compute_org_plans_and_status(
        org, inherited_plan_ids
    )
    vals = _build_org_vals(org, odoo_plan_ids, sunlight_status, member_tag_ids)

    if results:
        odoo_id = results[0]["id"]
        _diff_and_update_org(
            org, odoo_id, vals, odoo_plan_ids, sunlight_status, member_tag_ids, dry_run
        )
        return odoo_id, odoo_plan_ids
    else:
        if dry_run:
            logger.info("[DRY RUN] Would create org: %s (slug=%s)", org.name, org.slug)
            return None, odoo_plan_ids
        else:
            result = odoo_create("res.partner", vals)
            if not result:
                logger.error("Failed to create org in Odoo: %s", org.name)
                return None, odoo_plan_ids
            odoo_id = result[0]
            logger.info("Created org: %s", org.name)
            return odoo_id, odoo_plan_ids


def _member_desired_plans(user, org_plan_ids):
    """Union of the org's inherited plans and the user's own personal plans."""
    personal = list(user.individual_organization.plans.values_list("name", flat=True))
    personal_plan_ids = [
        pid for pid in (_resolve_plan_id(name) for name in personal) if pid is not None
    ]
    return sorted(set(org_plan_ids) | set(personal_plan_ids))


def _find_member(email):
    """Find an existing Odoo contact by primary, then secondary, email.
    Returns (odoo_id or None, matched_via_secondary)."""
    results = odoo_search(
        "res.partner",
        [["email", "=", email], ["is_company", "=", False]],
        ["id"],
    )
    if results:
        return results[0]["id"], False
    results = odoo_search(
        "res.partner",
        [["x_studio_secondary_email", "=", email], ["is_company", "=", False]],
        ["id"],
    )
    if results:
        return results[0]["id"], True
    return None, False


def _member_vals(user, odoo_org_id, matched_via_secondary):
    """Build the base res.partner vals for a member contact (no plans)."""
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
    return vals


def sync_member(user, org_name, odoo_org_id, org_plan_ids, dry_run=False):
    desired_plans = _member_desired_plans(user, org_plan_ids)
    odoo_id, matched_via_secondary = _find_member(user.email)
    vals = _member_vals(user, odoo_org_id, matched_via_secondary)

    if odoo_id is None:
        # create path: plans go straight in
        vals["x_studio_plan_1"] = [(6, 0, desired_plans)]
        if dry_run:
            logger.info(
                "[DRY RUN] Would create member: %s under org: %s (plans: %s)",
                user.email,
                org_name,
                desired_plans,
            )
        else:
            odoo_create("res.partner", vals)
            logger.info("Created member: %s (%s)", user.email, org_name)
        return

    _update_member(user, org_name, odoo_id, vals, desired_plans, dry_run)


def _update_member(user, org_name, odoo_id, vals, desired_plans, dry_run):
    # pylint:disable=too-many-positional-arguments
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
            "x_studio_plan_1",
        ],
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

    current_plans = sorted(set(current.get("x_studio_plan_1") or []))
    if current_plans != desired_plans:
        diffs["x_studio_plan_1"] = (current_plans, desired_plans)
        # (6, 0, ids) replaces all plans; desired_plans is the union of
        # org (inherited) and personal plans, so nothing is dropped
        vals["x_studio_plan_1"] = [(6, 0, desired_plans)]

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


def _unlink_departed_member(member, org, org_plans, dry_run):
    """Unlink a departed member and strip the plans they inherited from the org."""
    email = (member.get("email") or "").lower()
    current_plans = set(member.get("x_studio_plan_1") or [])
    inherited = current_plans & org_plans
    if dry_run:
        logger.info(
            "[DRY RUN] Would unlink departed member:"
            "%s (org: %s, would remove plans: %s)",
            email,
            org.name,
            sorted(inherited) or "none",
        )
        return
    write_vals = {"parent_id": False}
    if inherited:
        # (6, 0, ids) replaces all plans; keep everything except the
        # org-inherited plans being stripped on departure
        write_vals["x_studio_plan_1"] = [(6, 0, list(current_plans - inherited))]
    odoo_write("res.partner", [member["id"]], write_vals)
    logger.info(
        "Unlinked departed member: %s (org: %s, removed plans: %s)",
        email,
        org.name,
        sorted(inherited) or "none",
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
    org, odoo_org_id, org_plan_ids, remove=False, dry_run=False
):
    current_emails = {e.lower() for e in org.users.values_list("email", flat=True)}
    org_plans = set(org_plan_ids)

    odoo_members = odoo_search_all(
        "res.partner",
        [["parent_id", "=", odoo_org_id], ["is_company", "=", False]],
        [
            "id",
            "email",
            "x_studio_muckrock_accounts",
            "x_studio_org_departed_date",
            "x_studio_secondary_email",
            "x_studio_plan_1",
        ],
    )

    for member in odoo_members:
        if not _is_departed(member, current_emails):
            continue
        if remove:
            _unlink_departed_member(member, org, org_plans, dry_run)
        elif not member.get("x_studio_org_departed_date", False):
            _flag_departed_member(member, org, dry_run)


def cancel_org(odoo_id, name, dry_run=False):
    """Cancel a single Confirmed org."""
    if dry_run:
        logger.info("[DRY RUN] Would cancel lapsed org: %s (Odoo ID %s)", name, odoo_id)
    else:
        odoo_write(
            "res.partner",
            [odoo_id],
            {"x_studio_sunlight_status": "Cancelled"},
        )
        logger.info("Cancelled lapsed org: %s", name)


def _sweep_lapsed_orgs(active_slugs, dry_run=False, only_slug=None):
    """Find Confirmed Odoo orgs no longer active in Squarelet, cancel each."""
    logger.info(
        "Checking %d active Squarelet slugs against Odoo confirmed orgs",
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
        "Found %d confirmed orgs in Odoo with no active plan in Squarelet"
        " — these would be cancelled",
        len(candidates),
    )
    for org in candidates:
        cancel_org(org["id"], org["name"], dry_run=dry_run)


class CollaborativeConfig:
    """Holds resolved runtime data for a collaborative org."""

    def __init__(self, slug, tag_id, plan_ids, member_slugs):
        self.slug = slug
        self.tag_id = tag_id
        self.plan_ids = plan_ids
        self.member_slugs = member_slugs


def remove_collaborative_tag(tagged, config, dry_run=False):
    """Remove a collaborative tag and its inherited plans from a single org."""
    if dry_run:
        logger.info(
            "[DRY RUN] Would remove %s Member tag from: %s (Odoo ID %s)",
            config.slug,
            tagged["name"],
            tagged["id"],
        )
    else:
        write_vals = {"category_id": [(3, config.tag_id)]}
        current_plan_ids = set(tagged.get("x_studio_plan_1") or [])
        remaining = current_plan_ids - set(config.plan_ids)
        if remaining != current_plan_ids:
            write_vals["x_studio_plan_1"] = [(6, 0, sorted(remaining))]
        odoo_write("res.partner", [tagged["id"]], write_vals)
        logger.info("Removed %s Member tag from: %s", config.slug, tagged["name"])


def _sweep_stale_collaborative_tags(config, dry_run=False, only_slug=None):
    """Find orgs carrying a collaborative tag but no longer members, untag each."""
    domain = [["category_id", "in", [config.tag_id]], ["is_company", "=", True]]
    if only_slug is not None:
        domain.append(["x_studio_slug", "=", only_slug])
    tagged_orgs = odoo_search_all(
        "res.partner",
        domain,
        ["id", "name", "x_studio_slug", "x_studio_plan_1"],
    )
    for tagged in tagged_orgs:
        if (
            tagged["x_studio_slug"]
            and tagged["x_studio_slug"] not in config.member_slugs
        ):
            remove_collaborative_tag(tagged, config, dry_run=dry_run)


def _load_collaborative_data():
    """Load CollaborativeConfig for every collective-enabled org.
    Which orgs are collaboratives comes from the DB (collective_enabled);
    the Odoo tag id comes from settings.COLLABORATIVE_TAGS (slug -> tag id).
    A collective-enabled org with no configured tag is skipped with a warning."""
    collaborative_data = {}
    collab_orgs = Organization.objects.filter(
        collective_enabled=True,
        individual=False,
    ).prefetch_related("plans", "members")
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
        plan_ids = [
            pid
            for pid in (
                _resolve_plan_id(name)
                for name in collab_org.plans.filter(wix=True).values_list(
                    "name", flat=True
                )
            )
            if pid is not None
        ]
        member_slugs = set(collab_org.members.values_list("slug", flat=True))
        collaborative_data[collab_org.slug] = CollaborativeConfig(
            collab_org.slug, tag_id, plan_ids, member_slugs
        )
    return collaborative_data


def _build_org_queryset(collaborative_data):
    """Return the queryset of all orgs to sync."""
    sunlight_slugs = set(
        Organization.objects.filter(
            plans__wix=True,
            individual=False,
        )
        .values_list("slug", flat=True)
        .distinct()
    )
    all_collaborative_member_slugs = set()
    for config in collaborative_data.values():
        all_collaborative_member_slugs |= config.member_slugs
    all_slugs = (sunlight_slugs | all_collaborative_member_slugs) - SKIP_SLUGS
    return Organization.objects.filter(
        slug__in=all_slugs,
    ).prefetch_related("plans", "users", "urls")


def _sync_org(org, collaborative_data, dry_run, remove_members):
    """Sync a single org and its members. Returns the org slug if processed."""
    if org.slug in SKIP_SLUGS:
        return None

    member_tag_ids = []
    inherited_plan_ids = []
    labels = []
    for config in collaborative_data.values():
        if org.slug in config.member_slugs:
            member_tag_ids.append(config.tag_id)
            inherited_plan_ids.extend(config.plan_ids)
            labels.append(config.slug)

    label_str = "/".join(labels) + " member " if labels else ""
    logger.info("Syncing %sorg: %s", label_str, org.name)

    odoo_org_id, odoo_plan_ids = get_or_create_org(
        org,
        dry_run=dry_run,
        member_tag_ids=member_tag_ids or None,
        inherited_plan_ids=inherited_plan_ids or None,
    )

    if odoo_org_id is None:
        logger.info("Skipping members for %s — org not yet in Odoo", org.name)
        return org.slug

    memberships = Membership.objects.filter(organization=org).select_related("user")
    for membership in memberships:
        sync_member(
            membership.user, org.name, odoo_org_id, odoo_plan_ids, dry_run=dry_run
        )

    remove_departed_members(
        org, odoo_org_id, odoo_plan_ids, remove=remove_members, dry_run=dry_run
    )
    return org.slug


class Command(BaseCommand):
    """Sync Squarelet Sunlight orgs and members to Odoo"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without making changes",
        )
        parser.add_argument(
            "--remove-members",
            action="store_true",
            help="Unlink members from Odoo orgs if they are no longer in Squarelet",
        )
        parser.add_argument(
            "--slug",
            type=str,
            help="Limit sync to a single org by slug",
        )

    def handle(self, *args, **kwargs):  # pylint:disable=too-many-locals
        if not settings.ODOO_SYNC_ENABLED:
            self.stdout.write("ODOO_SYNC_ENABLED is not set; skipping sync.")
            return
        dry_run = kwargs["dry_run"]
        remove_members = kwargs["remove_members"]
        slug = kwargs.get("slug")
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        _prev_level = logger.level
        logger.setLevel(logging.INFO)
        failed = False
        try:
            if dry_run:
                logger.info("DRY RUN - no changes will be made")
            _ensure_all_plans(dry_run=dry_run)
            collaborative_data = _load_collaborative_data()
            all_orgs = _build_org_queryset(collaborative_data)
            if slug:
                all_orgs = all_orgs.filter(slug=slug)
            active_slugs = set()
            for org in all_orgs:
                processed_slug = _sync_org(
                    org, collaborative_data, dry_run, remove_members
                )
                if processed_slug:
                    active_slugs.add(processed_slug)
            _sweep_lapsed_orgs(active_slugs, dry_run=dry_run, only_slug=slug)
            for config in collaborative_data.values():
                if config.member_slugs:
                    _sweep_stale_collaborative_tags(
                        config, dry_run=dry_run, only_slug=slug
                    )
            logger.info("Sync complete")
        except Exception:
            failed = True
            logger.exception("Sync failed with an unhandled exception")
            raise
        finally:
            handler.flush()
            logger.removeHandler(handler)
            logger.setLevel(_prev_level)
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
