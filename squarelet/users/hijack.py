"""Function to control who has the ability to hijack"""


def hijack_by_group(hijacker, hijacked):
    """Certain groups my hijack"""

    hijack_groups = ["Support", "Technology"]

    if not hijacked.is_active:
        return False

    if hijacker.is_superuser:
        return True

    if hijacked.is_superuser:
        return False

    if hijacker.is_staff and hijacker.groups.filter(name__in=hijack_groups).exists():
        return True

    return False
