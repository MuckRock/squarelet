import csv

# Django
from django.http import HttpResponse
from django.contrib import admin

# Third Party
from reversion.admin import VersionAdmin

# Local
from .models import Statistics

def export_statistics_as_csv(modeladmin, request, queryset):
    """Export selected Statistics records to CSV."""
    field_names = [
        "date",
        "total_users",
        "total_users_excluding_agencies",
        "total_users_pro",
        "total_users_org",
        "total_orgs",
    ]

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = "attachment; filename=statistics.csv"

    writer = csv.writer(response)
    writer.writerow(field_names)

    for obj in queryset:
        writer.writerow([
            obj.date.isoformat(),
            obj.total_users,
            obj.total_users_excluding_agencies,
            obj.total_users_pro,
            obj.total_users_org,
            obj.total_orgs,
        ])

    return response


export_statistics_as_csv.short_description = "Export selected statistics to CSV"


@admin.register(Statistics)
class StatisticsAdmin(VersionAdmin):
    list_display = (
        "date",
        "total_users",
        "total_users_excluding_agencies",
        "total_users_pro",
        "total_users_org",
        "total_orgs",
    )
    readonly_fields = (
        "date",
        "total_users",
        "total_users_excluding_agencies",
        "total_users_pro",
        "total_users_org",
        "total_orgs",
        "users_today",
        "pro_users",
        "verified_orgs",
    )
    actions = [export_statistics_as_csv] 