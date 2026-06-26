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
from squarelet.organizations.models.organization import Membership, Organization

logger = logging.getLogger(__name__)

ODOO_URL = "https://muckrock-odoo.odoo.com"
ODOO_API_KEY = settings.ODOO_API_KEY

HEADERS = {
    "Authorization": f"bearer {ODOO_API_KEY}",
    "Content-Type": "application/json",
}

ODOO_TIMEOUT = 30

PLAN_SLUG_MAP = {
    "sunlight-basic": 97,
    "sunlight-basic-annual": 98,
    "sunlight-enhanced": 99,
    "sunlight-enhanced-annual": 100,
    "sunlight-enterprise": 101,
    "sunlight-enterprise-annual": 102,
    "sunlight-enterprise-rnn": 103,
    "sunlight-essential": 104,
    "sunlight-essential-annual": 105,
    "sunlight-nonprofit-enhanced": 106,
    "sunlight-nonprofit-enhanced-annual": 107,
    "sunlight-nonprofit-essential": 108,
    "sunlight-nonprofit-essential-annual": 109,
    "sunlight-premium": 110,
    "sunlight-premium-annual": 111,
    "election-accountability-cohort": 113,
    "premium-org-comp-election-hub": 92,
}

SKIP_SLUGS = {
    "sunlight-search",
    "reed-vs-wynne-city-of-et-al-case-324-cv-00198-kgb",
}

# Collaborative config: slug -> (tag_id, label)
COLLABORATIVES = {
    "rural-news-network": (1, "RNN"),
    "granite-state-news-collaborative-fiscally-sponsore": (3, "GSNC"),
}


def odoo_search(model, domain, fields, limit=1):
    resp = requests.post(
        f"{ODOO_URL}/json/2/{model}/search_read",
        headers=HEADERS,
        json={"domain": domain, "fields": fields, "limit": limit},
        timeout=ODOO_TIMEOUT,
    )
    return resp.json()


def odoo_create(model, vals):
    resp = requests.post(
        f"{ODOO_URL}/json/2/{model}/create",
        headers=HEADERS,
        json={"vals_list": [vals]},
        timeout=ODOO_TIMEOUT,
    )
    return resp.json()


def odoo_write(model, ids, vals):
    resp = requests.post(
        f"{ODOO_URL}/json/2/{model}/write",
        headers=HEADERS,
        json={"ids": ids, "vals": vals},
        timeout=ODOO_TIMEOUT,
    )
    return resp.json()


def _build_org_vals(org, odoo_plan_ids, sunlight_status, member_tag_ids):
    """Build the vals dict for a res.partner org record."""
    urls = list(org.urls.values_list("url", flat=True))
    vals = {
        "name": org.name,
        "x_studio_slug": org.slug,
        "x_studio_muckrock_accounts_id": org.id,
        "x_studio_muckrock_accounts_uuid": str(org.uuid),
        "city": org.city or "",
        "website": ", ".join(urls),
        "x_studio_verified_journalist": org.verified_journalist,
        "is_company": True,
        "company_type": "company",
        "x_studio_plan_1": [(6, 0, odoo_plan_ids)],
    }
    if sunlight_status is not None:
        vals["x_studio_sunlight_status"] = sunlight_status
    if member_tag_ids:
        vals["category_id"] = [(4, tag_id) for tag_id in member_tag_ids]
    if org.about:
        vals["x_studio_about"] = org.about
    return vals


def _compute_org_plans_and_status(org, inherited_plan_ids):
    """Return (odoo_plan_ids, sunlight_status) for an org."""
    plans = list(org.plans.values_list("name", "slug"))
    sunlight_plans = [
        name
        for name, slug in plans
        if "sunlight" in name.lower()
        or "election accountability cohort" in name.lower()
    ]
    own_plan_ids = [
        PLAN_SLUG_MAP[slug] for name, slug in plans if slug in PLAN_SLUG_MAP
    ]
    if inherited_plan_ids is not None:
        odoo_plan_ids = sorted(set(own_plan_ids + inherited_plan_ids))
    else:
        odoo_plan_ids = own_plan_ids
    sunlight_status = "Confirmed" if sunlight_plans else None
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
            odoo_id = result[0]
            logger.info("Created org: %s", org.name)
            return odoo_id, odoo_plan_ids


def sync_member_plans(odoo_org_id, org_plan_ids, dry_run=False):
    managed_plan_ids = set(PLAN_SLUG_MAP.values())
    members = odoo_search(
        "res.partner",
        [["parent_id", "=", odoo_org_id], ["is_company", "=", False]],
        ["id", "name", "x_studio_plan_1"],
        limit=200,
    )
    for member in members:
        current = set(member.get("x_studio_plan_1") or [])
        current_managed = current & managed_plan_ids
        org_plans = set(org_plan_ids)
        to_add = org_plans - current_managed
        to_remove = current_managed - org_plans
        if to_add or to_remove:
            new_ids = list((current | to_add) - to_remove)
            if dry_run:
                logger.info(
                    "[DRY RUN] Would update plans for member: %s — add: %s, remove: %s",
                    member["name"],
                    to_add,
                    to_remove,
                )
            else:
                odoo_write(
                    "res.partner",
                    [member["id"]],
                    {"x_studio_plan_1": [(6, 0, new_ids)]},
                )
                logger.info("Updated plans for member: %s", member["name"])


def sync_member(user, org_name, odoo_org_id, dry_run=False):
    results = odoo_search(
        "res.partner",
        [["email", "=", user.email], ["is_company", "=", False]],
        ["id", "parent_id"],
    )
    matched_via_secondary = False
    if not results:
        results = odoo_search(
            "res.partner",
            [
                ["x_studio_secondary_email", "=", user.email],
                ["is_company", "=", False],
            ],
            ["id", "parent_id"],
        )
        matched_via_secondary = bool(results)

    vals = {
        "name": user.name,
        "email": user.email,
        "parent_id": odoo_org_id,
        "is_company": False,
        "company_type": "person",
        "x_studio_muckrock_accounts": True,
    }

    if matched_via_secondary:
        del vals["email"]

    if results:
        odoo_id = results[0]["id"]
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
            ],
        )[0]
        current_parent = current.get("parent_id")
        current_parent_id = current_parent[0] if current_parent else None
        normalized = {
            "name": current["name"],
            "email": current["email"],
            "parent_id": current_parent_id,
            "is_company": current["is_company"],
            "company_type": current["company_type"],
            "x_studio_muckrock_accounts": current["x_studio_muckrock_accounts"],
        }
        diffs = {
            k: (normalized[k], v) for k, v in vals.items() if normalized.get(k) != v
        }
        if "parent_id" in diffs and normalized.get("parent_id") is not None:
            logger.info(
                "Note: %s already linked to parent ID %s, skipping reassignment to %s",
                user.email,
                normalized["parent_id"],
                odoo_org_id,
            )
            del diffs["parent_id"]
            del vals["parent_id"]
        if diffs:
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
        else:
            logger.info("No changes for member: %s (%s)", user.email, org_name)
    else:
        if dry_run:
            logger.info(
                "[DRY RUN] Would create member: %s under org: %s",
                user.email,
                org_name,
            )
        else:
            odoo_create("res.partner", vals)
            logger.info("Created member: %s (%s)", user.email, org_name)


def remove_departed_members(org, odoo_org_id, remove=False):
    current_emails = {e.lower() for e in org.users.values_list("email", flat=True)}

    odoo_members = odoo_search(
        "res.partner",
        [["parent_id", "=", odoo_org_id], ["is_company", "=", False]],
        [
            "id",
            "email",
            "x_studio_muckrock_accounts",
            "x_studio_org_departed_date",
            "x_studio_secondary_email",
        ],
        limit=200,
    )

    for member in odoo_members if isinstance(odoo_members, list) else []:
        primary = (member.get("email") or "").lower()
        secondary = (member.get("x_studio_secondary_email") or "").lower()
        if primary and (primary in current_emails or secondary in current_emails):
            continue
        if not primary:
            continue
        on_accounts = member.get("x_studio_muckrock_accounts", False)
        already_flagged = member.get("x_studio_org_departed_date", False)
        if remove:
            odoo_write("res.partner", [member["id"]], {"parent_id": False})
            logger.info("Unlinked departed member: %s (org: %s)", primary, org.name)
        else:
            if on_accounts and not already_flagged:
                odoo_write(
                    "res.partner",
                    [member["id"]],
                    {"x_studio_org_departed_date": date.today().isoformat()},
                )
                logger.info(
                    "Flagged departed member: %s (org: %s, departed: %s)",
                    primary,
                    org.name,
                    date.today().isoformat(),
                )
            elif not on_accounts:
                logger.info(
                    "Member in Odoo but never on Accounts: %s (org: %s)",
                    primary,
                    org.name,
                )


def cancel_lapsed_orgs(active_slugs, dry_run=False):
    logger.info(
        "Checking %d active Squarelet slugs against Odoo confirmed orgs",
        len(active_slugs),
    )
    results = odoo_search(
        "res.partner",
        [
            ["x_studio_sunlight_status", "=", "Confirmed"],
            ["is_company", "=", True],
            ["x_studio_slug", "not in", list(active_slugs | SKIP_SLUGS)],
        ],
        ["id", "name", "x_studio_plan_1"],
        limit=500,
    )

    logger.info(
        "Found %d confirmed orgs in Odoo with no active plan in Squarelet"
        " — these would be cancelled",
        len(results),
    )
    for org in results:
        if dry_run:
            logger.info(
                "[DRY RUN] Would cancel lapsed org: %s (Odoo ID %s)",
                org["name"],
                org["id"],
            )
        else:
            odoo_write(
                "res.partner",
                [org["id"]],
                {"x_studio_sunlight_status": "Cancelled"},
            )
            logger.info("Cancelled lapsed org: %s", org["name"])


class CollaborativeConfig:
    """Holds resolved runtime data for a collaborative org."""

    def __init__(self, tag_id, label, plan_ids, member_slugs):
        self.tag_id = tag_id
        self.label = label
        self.plan_ids = plan_ids
        self.member_slugs = member_slugs


def remove_stale_collaborative_tags(config, dry_run=False):
    """Remove collaborative tag (and plan if it was the only source)
    from orgs no longer in the collaborative."""
    tagged_orgs = odoo_search(
        "res.partner",
        [["category_id", "in", [config.tag_id]], ["is_company", "=", True]],
        ["id", "name", "x_studio_slug", "x_studio_plan_1"],
        limit=500,
    )
    for tagged in tagged_orgs:
        if (
            tagged["x_studio_slug"]
            and tagged["x_studio_slug"] not in config.member_slugs
        ):
            if dry_run:
                logger.info(
                    "[DRY RUN] Would remove %s Member tag from: %s (Odoo ID %s)",
                    config.label,
                    tagged["name"],
                    tagged["id"],
                )
            else:
                write_vals = {"category_id": [(3, config.tag_id)]}
                current_plan_ids = sorted(tagged.get("x_studio_plan_1") or [])
                if current_plan_ids == sorted(config.plan_ids):
                    write_vals["x_studio_plan_1"] = [(6, 0, [])]
                odoo_write("res.partner", [tagged["id"]], write_vals)
                logger.info(
                    "Removed %s Member tag from: %s",
                    config.label,
                    tagged["name"],
                )


def _load_collaborative_data():
    """Load CollaborativeConfig for each entry in COLLABORATIVES."""
    collaborative_data = {}
    for collab_slug, (tag_id, label) in COLLABORATIVES.items():
        try:
            collab_org = Organization.objects.get(slug=collab_slug)
            plan_ids = [
                PLAN_SLUG_MAP[s]
                for s in collab_org.plans.values_list("slug", flat=True)
                if s in PLAN_SLUG_MAP
            ]
            member_slugs = set(collab_org.members.values_list("slug", flat=True))
        except Organization.DoesNotExist:
            plan_ids = []
            member_slugs = set()
        collaborative_data[collab_slug] = CollaborativeConfig(
            tag_id, label, plan_ids, member_slugs
        )
    return collaborative_data


def _build_org_queryset(collaborative_data):
    """Return the queryset of all orgs to sync."""
    sunlight_slugs = set(
        Organization.objects.filter(
            plans__slug__in=list(PLAN_SLUG_MAP.keys()),
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
            labels.append(config.label)

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
        sync_member(membership.user, org.name, odoo_org_id, dry_run=dry_run)

    sync_member_plans(odoo_org_id, odoo_plan_ids, dry_run=dry_run)
    remove_departed_members(org, odoo_org_id, remove=remove_members)
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
        dry_run = kwargs["dry_run"]
        remove_members = kwargs["remove_members"]
        slug = kwargs.get("slug")

        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)

        try:
            if dry_run:
                logger.info("DRY RUN - no changes will be made")

            if slug:
                try:
                    all_orgs = [
                        Organization.objects.prefetch_related(
                            "plans", "users", "urls"
                        ).get(slug=slug)
                    ]
                    collaborative_data = {}
                except Organization.DoesNotExist:
                    self.stderr.write(f"No org found with slug: {slug}")
                    return
            else:
                collaborative_data = _load_collaborative_data()
                all_orgs = _build_org_queryset(collaborative_data)

            active_slugs = set()
            for org in all_orgs:
                processed_slug = _sync_org(
                    org, collaborative_data, dry_run, remove_members
                )
                if processed_slug:
                    active_slugs.add(processed_slug)

            for config in collaborative_data.values():
                if config.member_slugs:
                    remove_stale_collaborative_tags(config, dry_run=dry_run)

            if not slug:
                cancel_lapsed_orgs(active_slugs, dry_run=dry_run)

            logger.info("Sync complete")

        finally:
            logger.removeHandler(handler)
            today = date.today().isoformat()
            email = EmailMessage(
                subject=f"Odoo Sync Report - {today}",
                body="See attached for full sync report.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.ODOO_SYNC_REPORT_EMAIL],
            )
            email.attach(f"sync_report_{today}.txt", buffer.getvalue(), "text/plain")
            email.send()
