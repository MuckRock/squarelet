# Django
from django import template
from django.db.models import BooleanField, Value
from django.db.models.expressions import Case, When

# Squarelet
from squarelet.organizations.models import Organization

register = template.Library()


@register.inclusion_tag("templatetags/orgs_dropdown.html", takes_context=True)
def orgs_dropdown(context):
    request = context.get("request")
    if not request or not request.user.is_authenticated:
        return {"organizations": [], "is_authenticated": False}

    organizations = (
        Organization.objects.filter(
            users=request.user,
            individual=False,
        )
        .annotate(
            is_admin=Case(
                When(
                    memberships__user=request.user,
                    memberships__admin=True,
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by("-is_admin", "name")
        .distinct()
    )

    return {
        "organizations": organizations,
        "is_authenticated": True,
    }
