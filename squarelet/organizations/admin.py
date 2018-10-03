# Django
from django.contrib import admin

# Local
from .models import Organization, OrganizationMembership, ReceiptEmail


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    autocomplete_fields = ("user",)


class ReceiptEmailInline(admin.TabularInline):
    model = ReceiptEmail


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "org_type", "individual", "private")
    list_filter = ("org_type", "individual", "private")
    search_fields = ("name",)
    inlines = (OrganizationMembershipInline, ReceiptEmailInline)
