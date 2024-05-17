# Django
from django.contrib import admin

# Third Party
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.elections.models import ElectionResource


@admin.register(ElectionResource)
class ElectionResourceAdmin(VersionAdmin):
    list_display = (
        "name",
        "source",
        "category",
        "active",
    )
    list_filter = ("category", "active")
    search_fields = ("name", "source", "description")
    filter_horizontal = ("subtypes",)
    autocomplete_fields = ("members",)
