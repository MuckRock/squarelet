"""How an entitlement's resources turn into a quantity of something.

Two formulas live here, because during the migration both are true at
once: clients evaluate the first today and the second after they switch,
and the whole point of the entitlement shape migration is to reach a state
where they agree.  The pricing migration needs the first as well, to check
that repointing a subscription at a different plan has not changed what
its organization receives.
"""

PER_USER_SUFFIX = "_per_user"
BASE_PREFIX = "base_"


def scaling_pairs(resources):
    """The (per-unit key, flat key) pairs this entitlement scales on.

    `requests_per_user` pairs with `base_requests`, and so on.  An
    entitlement with no such pair - Sunlight's research hours, a bare
    `feature_level` - does not scale with quantity at all.
    """
    pairs = []
    for key in sorted(resources):
        if not key.endswith(PER_USER_SUFFIX):
            continue
        base_key = f"{BASE_PREFIX}{key[: -len(PER_USER_SUFFIX)]}"
        if base_key in resources:
            pairs.append((key, base_key))
    return pairs


def base_keys(resources):
    """Every `base_*` key, whether or not it has a per-unit partner.

    A flat entitlement - `{"base_requests": 50, "minimum_users": 5}` with no
    `requests_per_user` at all - still grants 50, and is exactly the shape
    the custom comped plans use.  Pairing on `_per_user` alone would make
    those invisible to the arithmetic that is supposed to protect them.
    """
    return sorted(key for key in resources if key.startswith(BASE_PREFIX))


def grants_old(resources, quantity):
    """What a client grants today, per resource key.

    `base + max(quantity - minimum_users, 0) * per_user`, with an absent
    per-unit key read as zero - which is how the formula behaves anyway.
    """
    minimum = resources.get("minimum_users", 0)
    return {
        base_key: resources[base_key]
        + max(quantity - minimum, 0)
        * resources.get(f"{base_key[len(BASE_PREFIX):]}{PER_USER_SUFFIX}", 0)
        for base_key in base_keys(resources)
    }


def grants_new(resources, quantity):
    """What a client will grant once it switches: `base * quantity`."""
    return {
        base_key: resources[base_key] * quantity for base_key in base_keys(resources)
    }


def grant_old(resources, quantity):
    """`grants_old` totalled - convenient when there is only one key."""
    return sum(grants_old(resources, quantity).values())


def grant_new(resources, quantity):
    """`grants_new` totalled - convenient when there is only one key."""
    return sum(grants_new(resources, quantity).values())


def reshape(resources, *, is_pack):
    """The target shape, in which both formulas give the same number.

    `minimum_users = 1` and `per_user = base` makes
    `base + max(q - 1, 0) * base` identically `base * q` for every q >= 1.

    A pack starts inverted - its value lives in `per_user` with `base` at
    zero, because that is the only shape the *current* formula can scale -
    so the value moves the other way.  Applying the tier transform to a
    pack would set `per_user = 0` and grant nothing at all, which is the
    trap migration 0082 wrote itself a note about.
    """
    new = dict(resources)
    pairs = scaling_pairs(resources)
    if not pairs:
        return new
    for per_user_key, base_key in pairs:
        if is_pack:
            new[base_key] = resources[per_user_key]
        else:
            new[per_user_key] = resources[base_key]
    new["minimum_users"] = 1
    return new
