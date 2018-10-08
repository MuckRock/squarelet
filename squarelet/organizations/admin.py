# Django
from django.contrib import admin

# Local
from .models import Invitation, Organization, OrganizationMembership, ReceiptEmail


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    autocomplete_fields = ("user",)
    extra = 0


class ReceiptEmailInline(admin.TabularInline):
    model = ReceiptEmail
    extra = 0


class InvitationInline(admin.TabularInline):
    model = Invitation
    autocomplete_fields = ("user",)
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "org_type", "individual", "private")
    list_filter = ("org_type", "individual", "private")
    search_fields = ("name",)
    inlines = (OrganizationMembershipInline, ReceiptEmailInline, InvitationInline)
