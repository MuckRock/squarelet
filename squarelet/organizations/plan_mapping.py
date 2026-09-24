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
}

# Left on their legacy plans until someone decides.
DEFERRED_SLUGS = {
    # Two organizations going opposite ways: one cancelled, one comped.
    "custom-crp",
    # Its one subscription belongs to an organization that was merged away.
    "sunlight-premium-annual",
}


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
