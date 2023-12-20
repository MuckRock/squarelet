# Django
from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe

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
    OrganizationEmailDomain,
    OrganizationSubtype,
    OrganizationType,
    OrganizationUrl,
    Plan,
    ReceiptEmail,
    Subscription,
)
from squarelet.users.models import User


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    readonly_fields = ("plan", "subscription_id", "update_on", "cancelled")
    extra = 0


class CustomerInline(admin.TabularInline):
    model = Customer
    readonly_fields = ("customer_id",)
    extra = 0


class MembershipInline(admin.TabularInline):
    model = Membership
    autocomplete_fields = ("user",)
    extra = 0


class ReceiptEmailInline(admin.TabularInline):
    model = ReceiptEmail
    extra = 0


class OrganizationEmailDomainInline(admin.TabularInline):
    model = OrganizationEmailDomain
    extra = 1


class OrganizationUrlInline(admin.TabularInline):
    model = OrganizationUrl
    extra = 1


class InvitationInline(admin.TabularInline):
    model = Invitation
    autocomplete_fields = ("user",)
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(VersionAdmin):
    list_display = (
        "name",
        "individual",
        "private",
        "verified_journalist",
        "get_subtypes",
    )
    list_filter = ("individual", "private", "verified_journalist", "subtypes")
    search_fields = ("name",)
    fields = (
        "uuid",
        "name",
        "slug",
        "created_at",
        "updated_at",
        "avatar",
        "individual",
        "private",
        "verified_journalist",
        "max_users",
        "payment_failed",
        "subtypes",
        "members",
        "parent",
        "wikidata_id",
    )
    readonly_fields = (
        "uuid",
        "slug",
        "max_users",
        "created_at",
        "updated_at",
        "individual",
    )
    filter_horizontal = ("subtypes",)
    autocomplete_fields = ("members", "parent")
    save_on_top = True
    inlines = (
        OrganizationUrlInline,
        OrganizationEmailDomainInline,
        SubscriptionInline,
        CustomerInline,
        MembershipInline,
        ReceiptEmailInline,
        InvitationInline,
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("subtypes")

    def save_model(self, request, obj, form, change):
        if obj.verified_journalist and "verified_journalist" in form.changed_data:
            obj.subscribe()
        super().save_model(request, obj, form, change)

    def get_fields(self, request, obj=None):
        """Only add user link for individual organizations"""
        if obj and obj.individual:
            return ("user_link",) + self.fields
        else:
            return self.fields

    def get_readonly_fields(self, request, obj=None):
        """Only add user link for individual organizations"""
        if obj and obj.individual:
            return ("user_link",) + self.readonly_fields
        else:
            return self.readonly_fields

    @mark_safe
    def user_link(self, obj):
        """Link to the individual org's user"""
        user = User.objects.get(individual_organization_id=obj.uuid)
        link = reverse("admin:users_user_change", args=(user.pk,))
        return f'<a href="{link}">{user.username}</a>'

    user_link.short_description = "User"

    def get_subtypes(self, obj):
        return ", ".join(s.name for s in obj.subtypes.all())

    get_subtypes.short_description = "Subtypes"


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
    list_filter = ("client",)
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


class OrganizationSubtypeInline(admin.TabularInline):
    model = OrganizationSubtype
    extra = 1


@admin.register(OrganizationType)
class OrganizationTypeAdmin(VersionAdmin):
    list_display = ("name",)
    inlines = (OrganizationSubtypeInline,)
