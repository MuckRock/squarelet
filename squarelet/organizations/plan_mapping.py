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
