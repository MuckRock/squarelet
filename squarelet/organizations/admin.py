# Django
from django.contrib import admin

# Local
from .models import Invitation, Membership, Organization, ReceiptEmail


class MembershipInline(admin.TabularInline):
    model = Membership
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
    list_display = ("name", "plan", "individual", "private")
    list_filter = ("plan", "individual", "private")
    search_fields = ("name",)
    inlines = (MembershipInline, ReceiptEmailInline, InvitationInline)
