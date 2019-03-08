# Django
from django.contrib import admin

# Third Party
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import Charge

# Local
from .models import Invitation, Membership, Organization, Plan, ReceiptEmail


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
class OrganizationAdmin(VersionAdmin):
    list_display = ("name", "plan", "individual", "private")
    list_filter = ("plan", "individual", "private")
    list_select_related = ("plan",)
    search_fields = ("name",)
    readonly_fields = (
        "plan",
        "next_plan",
        "max_users",
        "customer_id",
        "subscription_id",
    )
    inlines = (MembershipInline, ReceiptEmailInline, InvitationInline)


@admin.register(Plan)
class PlanAdmin(VersionAdmin):
    list_display = (
        "name",
        "slug",
        "minimum_users",
        "base_price",
        "price_per_user",
        "feature_level",
        "public",
        "annual",
        "for_individuals",
        "for_groups",
    )
    search_fields = ("name",)
    autocomplete_fields = ("private_organizations",)


@admin.register(Charge)
class ChargeAdmin(VersionAdmin):
    list_display = ("organization", "amount", "created_at", "description")
    list_select_related = ("organization",)
    search_fields = ("organization__name", "description")
    date_hierarchy = "created_at"
    readonly_fields = ("organization", "amount", "created_at", "charge_id")
