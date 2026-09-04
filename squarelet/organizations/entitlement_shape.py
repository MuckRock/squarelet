"""How an entitlement's resources turn into a quantity of something."""

PER_USER_SUFFIX = "_per_user"
BASE_PREFIX = "base_"


def scaling_pairs(resources):
    """The (per-unit key, flat key) pairs this entitlement scales on.

    An entitlement with no pair, such as Sunlight's research hours, does not
    scale with quantity.
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
    """Every `base_*` key, including flat ones with no per-unit partner."""
    return sorted(key for key in resources if key.startswith(BASE_PREFIX))


def grants_old(resources, quantity):
    """What the clients grant today: `base + max(quantity - minimum, 0) * per_user`."""
    minimum = resources.get("minimum_users", 0)
    return {
        base_key: resources[base_key]
        + max(quantity - minimum, 0)
        * resources.get(f"{base_key[len(BASE_PREFIX):]}{PER_USER_SUFFIX}", 0)
        for base_key in base_keys(resources)
    }


def grants_new(resources, quantity):
    """What the clients grant once they switch: `base * quantity`."""
    return {
        base_key: resources[base_key] * quantity for base_key in base_keys(resources)
    }


def grant_old(resources, quantity):
    """`grants_old` totalled, for an entitlement with one key."""
    return sum(grants_old(resources, quantity).values())


def grant_new(resources, quantity):
    """`grants_new` totalled, for an entitlement with one key."""
    return sum(grants_new(resources, quantity).values())


def reshape(resources, *, is_pack):
    """The shape in which both formulas give the same number.

    `minimum_users = 1` and `per_user = base` make `base + max(q - 1, 0) * base`
    equal `base * q` for every q >= 1.  A pack's value lives in `per_user` with
    `base` at zero, so it moves the other way; the tier transform would zero it.
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
