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
