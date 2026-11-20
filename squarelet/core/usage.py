# Squarelet
from squarelet.services.models import Service
from squarelet.users.models import User

# Resources to display on the user/org detail page. Matches the shape of client_stats.
# Each resource is a (key, singular label) tuple.
USAGE_RESOURCES = {
    "muckrock": [("requests", "request")],
    "documentcloud": [("ai_credits", "AI credit")],
}


def get_usage_stats(user_or_org, other_orgs):
    """Get resource balances for each resource the subject has or inherits."""

    # pylint: disable=too-many-locals

    prefix = "individual_" if isinstance(user_or_org, User) else ""

    own_stats = user_or_org.client_stats or {}
    org_stats = [org.client_stats or {} for org in other_orgs]

    services = Service.objects.in_bulk(USAGE_RESOURCES.keys(), field_name="slug")

    usage = {}

    for service, resources in USAGE_RESOURCES.items():
        own_service = own_stats.get(service) or {}
        org_services = [stats[service] for stats in org_stats if stats.get(service)]

        if not own_service and not org_services:
            continue

        service_name = services[service].name if service in services else service

        for resource, label in resources:
            own = own_service.get(f"{prefix}{resource}") or {}
            inherited_stats = [stats.get(resource) or {} for stats in org_services]

            allowance = own.get(f"{resource}_per_month") or 0
            used = allowance - (own.get(f"monthly_{resource}") or 0)
            purchased = own.get(f"number_{resource}") or 0
            # Remaining monthly and purchased resource count across all orgs
            inherited = sum(
                (org.get(f"number_{resource}") or 0)
                + (org.get(f"monthly_{resource}") or 0)
                for org in inherited_stats
            )

            if allowance > 0 or purchased > 0 or inherited > 0:
                usage.setdefault(service_name, {})[label] = {
                    "allowance_monthly": allowance,
                    "used_monthly": used,
                    "available_purchased": purchased,
                    "available_inherited": inherited,
                }

    return usage
