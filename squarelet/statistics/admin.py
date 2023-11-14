# Django
from django.contrib import admin

# Third Party
from reversion.admin import VersionAdmin

# Local
from .models import Statistics


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
