# Django
from django.contrib import admin

# Third Party
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import (
    Charge,
    Customer,
    Entitlement,
    Invitation,
    Membership,
    Organization,
    OrganizationChangeLog,
    Plan,
    ReceiptEmail,
    Subscription,
)


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    readonly_fields = ("plan", "subscription_id", "update_on", "cancelled")
    extra = 0


class CustomerInline(admin.TabularInline):
    model = Customer
    readonly_fields = ("stripe_account", "customer_id")
    extra = 0


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
    list_display = ("name", "individual", "private")
    list_filter = ("individual", "private")
    search_fields = ("name",)
    readonly_fields = ("max_users", "customer_id", "subscription_id")
    inlines = (
        SubscriptionInline,
        CustomerInline,
        MembershipInline,
        ReceiptEmailInline,
        InvitationInline,
    )


@admin.register(Plan)
class PlanAdmin(VersionAdmin):
    list_display = (
        "name",
        "slug",
        "minimum_users",
        "base_price",
        "price_per_user",
        "public",
        "annual",
        "for_individuals",
        "for_groups",
    )
    search_fields = ("name",)
    autocomplete_fields = ("private_organizations", "entitlements")


@admin.register(Entitlement)
class EntitlementAdmin(VersionAdmin):
    list_display = ("name", "client")
    search_fields = ("name",)
    autocomplete_fields = ("client",)


@admin.register(Charge)
class ChargeAdmin(VersionAdmin):
    list_display = ("organization", "amount", "created_at", "description")
    list_select_related = ("organization",)
    search_fields = ("organization__name", "description")
    date_hierarchy = "created_at"
    readonly_fields = ("organization", "amount", "created_at", "charge_id")


@admin.register(OrganizationChangeLog)
class OrganizationChangeLogAdmin(VersionAdmin):
    list_display = (
        "organization",
        "created_at",
        "user",
        "reason",
        "from_plan",
        "from_next_plan",
        "from_max_users",
        "to_plan",
        "to_next_plan",
        "to_max_users",
    )
    list_select_related = (
        "organization",
        "user",
        "from_plan",
        "from_next_plan",
        "to_plan",
        "to_next_plan",
    )
    date_hierarchy = "created_at"
    readonly_fields = (
        "organization",
        "created_at",
        "user",
        "reason",
        "from_plan",
        "from_next_plan",
        "from_max_users",
        "to_plan",
        "to_next_plan",
        "to_max_users",
    )
    search_fields = ("organization__name",)
    list_filter = (
        "reason",
        "organization__individual",
        "from_plan",
        "from_next_plan",
        "to_plan",
        "to_next_plan",
    )
