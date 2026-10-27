# Django
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.dateparse import parse_datetime
from django.utils.timesince import timesince
from django.utils.translation import gettext_lazy as _, ngettext_lazy

# Standard Library
from dataclasses import dataclass

# Squarelet
from squarelet.services.models import Service

register = template.Library()


@dataclass(frozen=True)
class ServiceMetric:
    total_key: str
    last_key: str
    count_label: object
    empty: str
    last_label: str
    # Shown regardless of usage; otherwise only when used or verified.
    always_show: bool


# Keys match both the `client_stats` keys and the `Service` slugs, in display order.
SERVICE_METRICS = {
    "muckrock": ServiceMetric(
        total_key="total_requests",
        last_key="last_request_at",
        count_label=ngettext_lazy("%(total)s request", "%(total)s requests", "count"),
        empty=_("No requests"),
        last_label=_("Last request"),
        always_show=True,
    ),
    "documentcloud": ServiceMetric(
        total_key="total_documents",
        last_key="last_upload_at",
        count_label=ngettext_lazy("%(total)s document", "%(total)s documents", "count"),
        empty=_("No documents"),
        last_label=_("Last upload"),
        always_show=False,
    ),
}


def service_usage(entity, subject, verified):
    """One line per service the profile card shows, in display order.

    Services without a matching `Service` row are skipped, since the line has
    no icon or name to show without one.
    """
    client_stats = entity.client_stats or {}
    services = Service.objects.in_bulk(list(SERVICE_METRICS), field_name="slug")
    lines = []
    for slug, metric in SERVICE_METRICS.items():
        service = services.get(slug)
        if service is None:
            continue
        stats = client_stats.get(slug) or {}
        total = stats.get(metric.total_key) or 0
        if not (metric.always_show or total or verified):
            continue
        label = (
            metric.count_label % {"count": total, "total": intcomma(total)}
            if total
            else metric.empty
        )
        last_at = stats.get(metric.last_key)
        last_at = parse_datetime(last_at) if last_at else None
        lines.append(
            {
                "service": service,
                "url": service.url_for(subject, entity.uuid),
                "label": label,
                "last_label": metric.last_label,
                "last_at": last_at,
                "last_since": timesince(last_at, depth=1) if last_at else "",
            }
        )
    return lines


def _location(organization):
    parts = [organization.city, organization.get_state_display()]
    if organization.country != "US":
        parts.append(organization.get_country_display())
    return ", ".join(part for part in parts if part)


@register.inclusion_tag("templatetags/profile_card.html")
def profile_card(entity, subject, verified=False, show_stats=False):
    """Profile summary for a user (subject="users") or organization."""
    if subject == "users":
        context = {
            "title": entity.name or entity.username,
            "subtitle": entity.username if entity.name else "",
            "joined_at": entity.created_at,
            "fallback_icon": "person-24",
        }
    else:
        context = {
            "title": entity.name,
            "subtitle": _location(entity),
            "about": entity.about,
            "fallback_icon": "people-24",
        }
    context.update(
        {
            "avatar": entity.avatar,
            "verified": verified,
            "service_lines": (
                service_usage(entity, subject, verified) if show_stats else []
            ),
        }
    )
    return context
