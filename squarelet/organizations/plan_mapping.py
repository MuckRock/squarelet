"""Where each legacy plan lands under the consolidated pricing model.

Shared by the migration and by purchases, so a new line is recorded exactly
as a migrated one.
"""

# Keyed on (legacy slug, is billing): admins comped organizations by putting
# them on a paid plan with no Stripe subscription.  Each target bills what the
# legacy plan did.  Values are (canonical slug, interval, label, code).
LEGACY_PLAN_MAP = {
    # MuckRock Professional
    ("professional", True): ("professional", "monthly", "standard", ""),
    ("professional", False): ("professional", "monthly", "comped", ""),
    ("professional-pre-paid", True): ("professional", "annual", "standard", ""),
    # The one DocumentCloud-only tier, which keeps its own plan.
    ("documentcloud-premium", True): (
        "documentcloud-premium",
        "monthly",
        "standard",
        "",
    ),
    # Tiers that were never legacy plans: each is its own target.
    ("scoutpost-pro", True): ("scoutpost-pro", "monthly", "standard", ""),
    ("scoutpost-team", True): ("scoutpost-team", "monthly", "standard", ""),
    # Grandfathered early users
    ("beta", False): ("professional", "monthly", "comped", ""),
    ("beta", True): ("professional", "monthly", "comped", ""),
    # MuckRock Organization
    ("organization", False): ("organization", "monthly", "comped", ""),
    # Comped organizations, each on a plan of its own
    ("muckrock-editorial-partner", False): (
        "organization",
        "monthly",
        "comped",
        "",
    ),
    ("premium-org-comp", False): ("organization", "monthly", "comped", ""),
    ("education-grant", False): ("organization", "monthly", "comped", ""),
    ("startsmall-grants", False): ("organization", "monthly", "comped", ""),
    ("education-plan", False): ("organization", "monthly", "comped", ""),
    # $0 for 200 blocks, invoiced by hand.
    ("organization-flexible-users-annual", False): (
        "organization",
        "monthly",
        "comped",
        "",
    ),
    # Organization in all but 5 requests per block, and neither subscriber
    # holds a block.
    ("custom-crp", True): ("organization", "monthly", "standard", ""),
    # A negotiated rate, so a price of its own rather than a coupon
    ("insideclimate-news-plan", True): (
        "organization",
        "monthly",
        "standard",
        "insideclimate",
    ),
    # Sunlight
    ("sunlight-enterprise-rnn", False): (
        "sunlight-enterprise",
        "annual",
        "comped",
        "",
    ),
    # The only plan granting staff access across all three products
    ("admin", False): ("admin", "monthly", "comped", ""),
    # --- Plans a new customer can still pick -------------------------------
    ("organization", True): ("organization", "monthly", "standard", ""),
    ("sunlight-essential", True): ("sunlight-essential", "monthly", "standard", ""),
    # Annual is a separate Plan row; it lands on its tier's annual price.
    ("sunlight-essential-annual", True): (
        "sunlight-essential",
        "annual",
        "standard",
        "",
    ),
    ("sunlight-enhanced", True): ("sunlight-enhanced", "monthly", "standard", ""),
    ("sunlight-enhanced-annual", True): ("sunlight-enhanced", "annual", "standard", ""),
    # The form substitutes these in when the nonprofit box is ticked.
    ("sunlight-nonprofit-essential", True): (
        "sunlight-essential",
        "monthly",
        "nonprofit",
        "",
    ),
    ("sunlight-nonprofit-essential-annual", True): (
        "sunlight-essential",
        "annual",
        "nonprofit",
        "",
    ),
    ("sunlight-nonprofit-enhanced", True): (
        "sunlight-enhanced",
        "monthly",
        "nonprofit",
        "",
    ),
    ("sunlight-nonprofit-enhanced-annual", True): (
        "sunlight-enhanced",
        "annual",
        "nonprofit",
        "",
    ),
    # --- Private plans ------------------------------------------------------
    ("organization-annual", True): ("organization", "annual", "standard", ""),
    ("sunlight-enterprise-annual", True): (
        "sunlight-enterprise",
        "annual",
        "standard",
        "",
    ),
    # Negotiated rates: prices of their own, not coupons, since neither
    # expires.  The cohort's interval here is nominal; its subscribers bill at
    # both cadences.
    ("election-accountability-cohort", True): (
        "sunlight-essential",
        "annual",
        "standard",
        "election-cohort",
    ),
    ("sunlight-basic-annual", True): (
        "sunlight-essential",
        "annual",
        "standard",
        "legacy-basic",
    ),
}

# Plans the migration leaves on their legacy rows.
DEFERRED_SLUGS = set()

# Bills at both cadences, which one map entry cannot say.
COHORT_SLUG = "election-accountability-cohort"

# Which pack a legacy plan's resource blocks become, for the plans production
# has block-holders on; the migration refuses any other.
PACK_DECOMPOSITION = {
    "organization": ("muckrock-request-pack",),
    "organization-annual": ("muckrock-request-pack",),
    "organization-flexible-users-annual": ("muckrock-request-pack",),
    "documentcloud-premium": ("documentcloud-credit-pack",),
}

# What a block granted that no pack carries, and may be dropped: DocumentCloud
# credits (37 used by all block-holders, ever).
DROPPED_WITH_BLOCKS = frozenset({"base_ai_credits"})

# Legacy plans whose grant changes on purpose when they consolidate.  Any
# other change stops the migration.
EXPECTED_GRANT_CHANGES = {
    "beta": "Grandfathered onto Professional: 5 -> 20 MuckRock requests.",
    "insideclimate-news-plan": (
        "Normalized to Organization: 15 -> 50 requests, plus DocumentCloud "
        "access it does not have today."
    ),
    "education-plan": (
        "Gains Organization's 50 requests, where org-features-minus-requests "
        "grants zero, plus DocumentCloud access."
    ),
}


def tier_of(slug):
    """The canonical plan a plan slug lands on, comped included; itself if unmapped."""
    for billing in (True, False):
        target = LEGACY_PLAN_MAP.get((slug, billing))
        if target is not None:
            return target[0]
    return slug


def resolve_target(slug):
    """What a purchase of `slug` is sold as: (canonical slug, interval, label, code).

    None for an unmapped slug, which is sold as itself, and for a comped
    target, since a purchase must never be free.  A negotiated `code` is
    allowed: reaching one takes being granted its plan.
    """
    target = LEGACY_PLAN_MAP.get((slug, True))
    if target is None or target[2] == "comped":
        return None
    return target
