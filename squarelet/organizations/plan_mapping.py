"""Where each legacy plan lands under the consolidated pricing model.

Lives here rather than inside the migration command because two callers
need it and they want different things from it:

- the migration asks "where does this existing subscription land", and the
  answer legitimately includes comped and negotiated outcomes;
- the sign-up flow asks "what does this cost a new customer", which must
  never resolve to comped.

Keeping one table avoids two descriptions of the same relationship
drifting apart; `resolve_target` below is what keeps the second caller
honest.
"""

# Where each legacy plan's subscriptions land, keyed on the legacy slug and
# whether the subscription is actually billing.
#
# The slug alone is not enough.  Admins granted free access for years by
# putting organizations on a paid plan without a Stripe subscription, so
# `organization` means the standard price for its paying subscribers and the
# comped price for those.  `is_billing` - whether a Stripe subscription
# exists - is what separates them.
#
# Every target was chosen against the legacy plan it replaces so that no
# subscriber's bill changes.  Values are (canonical slug, interval, label,
# code).
LEGACY_PLAN_MAP = {
    # MuckRock Professional
    ("professional", True): ("professional", "monthly", "standard", ""),
    ("professional", False): ("professional", "monthly", "comped", ""),
    ("professional-pre-paid", True): ("professional", "annual", "standard", ""),
    # Beta - early users grandfathered onto a free plan, not a distinct tier
    ("beta", False): ("professional", "monthly", "comped", ""),
    ("beta", True): ("professional", "monthly", "comped", ""),
    # MuckRock Organization
    ("organization", False): ("organization", "monthly", "comped", ""),
    # Comped organizations, previously each with their own plan
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
    # Admin keeps its own plan - the only one granting staff access across
    # all three products - and simply gains a comped price.
    ("admin", False): ("admin", "monthly", "comped", ""),
    # --- Plans a new customer can still pick -------------------------------
    #
    # These are not legacy rows being consolidated away; they are the tiers
    # themselves, and they are here because a purchase resolves through this
    # same table.  Annual is a separate `Plan` row today rather than an
    # interval, so it maps onto the canonical tier with interval="annual" -
    # which is exactly what the migration does with them too.
    ("organization", True): ("organization", "monthly", "standard", ""),
    ("sunlight-essential", True): ("sunlight-essential", "monthly", "standard", ""),
    ("sunlight-essential-annual", True): (
        "sunlight-essential",
        "annual",
        "standard",
        "",
    ),
    ("sunlight-enhanced", True): ("sunlight-enhanced", "monthly", "standard", ""),
    ("sunlight-enhanced-annual", True): ("sunlight-enhanced", "annual", "standard", ""),
    # Nonprofit variants are not public - `get_selected_plan()` substitutes
    # one in when the checkbox is ticked - so a purchase arrives here already
    # on the variant slug.  Mapping them means the label comes out right
    # without the form having to change.
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
    # --- Per-user plans, which decompose rather than simply repoint --------
    #
    # These land on a flat tier price exactly like the rows above; what makes
    # them different is that the line also carries a block count, so the
    # migration adds pack lines alongside.  The target here covers the base
    # only.  See PACK_DECOMPOSITION for the blocks.
    ("organization-annual", True): ("organization", "annual", "standard", ""),
    ("sunlight-enterprise-annual", True): (
        "sunlight-enterprise",
        "annual",
        "standard",
        "",
    ),
    # The older, cheaper Sunlight Basic rate, kept for the subscribers who
    # still hold it.  A permanent grandfather rate is what the subscription
    # costs rather than a discount that expires, so it is a price with a
    # `code` and not a coupon.
    ("sunlight-basic-annual", True): (
        "sunlight-essential",
        "annual",
        "standard",
        "legacy-basic",
    ),
}

# Which packs one resource block becomes, per legacy plan.
#
# A block was never a single product's unit: it granted MuckRock requests
# *and* DocumentCloud credits together.  Packs are sold per product, so how
# many a block turns into is a per-plan fact and cannot be derived from the
# block count alone.
#
# Only these two plans need an entry.  Twelve organizations hold blocks over
# their minimum in production and every one of them is on Organization or
# Organization (Annual) - checked against live data, not inferred.  Nobody
# else can join them: the purchase flow hardcodes `minimum_users`, so
# self-service cannot sell a block at all.  Listing the Sunlight tiers too
# would be writing down a guess nothing exercises; if a block-holder ever
# does appear on one, the migration refuses to run until it is added.
#
# An Organization block costs one pack ($10/mo, $120/yr) and becomes one.
# Preserving the DocumentCloud half would double what those subscribers pay,
# and the overage went essentially unused - 37 credits across all twelve for
# all time, against a 30,000/month grant.  Dropping it is what keeps the
# bill identical without a coupon or a conversation.
#
# None of this is trusted on faith: the migration recomputes each
# subscriber's bill both ways and refuses anyone the arithmetic does not
# reproduce exactly.
PACK_DECOMPOSITION = {
    "organization": ("muckrock-request-pack",),
    "organization-annual": ("muckrock-request-pack",),
}

# Deliberately left alone.  Each needs a decision or an action outside this
# command, given per entry below.
DEFERRED_SLUGS = {
    # Two organizations going opposite ways - one cancelled, one comped - so
    # the slug alone cannot decide.
    "custom-crp",
    # Its one subscription belongs to an organization that was merged away.
    "sunlight-premium-annual",
}


def resolve_target(slug, *, allow_comped):
    """The canonical (slug, interval, label, code) for a legacy plan slug.

    Returns None when the slug is unmapped, which callers treat as "leave
    it on the legacy plan" rather than as an error.

    `allow_comped` is the distinction between the two callers.  A comped
    target is correct for a subscription that is *already* comped and is
    being migrated; it is never correct for a new self-service purchase,
    which would be handing out a free subscription.  Negotiated (`code`)
    targets are deliberately allowed for both: reaching one requires being
    granted the private plan in the first place, and that grant is the
    authorisation.
    """
    target = LEGACY_PLAN_MAP.get((slug, True))
    if target is None:
        return None
    if not allow_comped and target[2] == "comped":
        return None
    return target


# Legacy plans whose entitlements deliberately change when they consolidate.
#
# Repointing a subscription moves it onto the canonical tier's entitlements,
# which is usually a no-op by construction.  Where it is not, the change was
# a decision rather than an accident, and the migration reports it instead of
# refusing.  Everything absent from this map must come out identical.
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
