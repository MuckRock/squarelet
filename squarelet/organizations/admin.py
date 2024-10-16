# Django
from django.contrib import admin
from django.forms.models import BaseInlineFormSet
from django.http.response import HttpResponse
from django.urls import reverse
from django.utils.safestring import mark_safe

# Standard Library
import csv

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


class MembershipFormset(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queryset = self.queryset.select_related("user", "organization")


class MembershipInline(admin.TabularInline):
    model = Membership
    readonly_fields = ("user",)
    fields = ["user", "admin"]
    extra = 0
    formset = MembershipFormset


class ReceiptEmailInline(admin.TabularInline):
    model = ReceiptEmail
    extra = 0


class OrganizationEmailDomainInline(admin.TabularInline):
    model = OrganizationEmailDomain
    extra = 1


class OrganizationUrlInline(admin.TabularInline):
    model = OrganizationUrl
    extra = 1


class InvitationFormset(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queryset = self.queryset.select_related("user", "organization")


class InvitationInline(admin.TabularInline):
    model = Invitation
    readonly_fields = ("user",)
    fields = ["email", "user", "request", "accepted_at", "rejected_at"]
    extra = 0
    formset = InvitationFormset


class ChildrenInline(admin.TabularInline):
    model = Organization
    fk_name = "parent"
    fields = ("name",)
    readonly_fields = ("name",)
    verbose_name = "Child"
    verbose_name_plural = "Children"
    can_delete = False
    show_change_link = True
    max_num = 0
    extra = 0


class MembershipsInline(admin.TabularInline):
    model = Organization.members.through
    fk_name = "to_organization"
    verbose_name = "Membership"
    verbose_name_plural = "Memberships"
    autocomplete_fields = ("from_organization",)


@admin.register(Organization)
class OrganizationAdmin(VersionAdmin):
    list_display = (
        "name",
        "individual",
        "private",
        "verified_journalist",
        "get_subtypes",
    )
    list_filter = (
        "individual",
        "private",
        "verified_journalist",
        "hub_eligible",
        "subtypes",
    )
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
        "hub_eligible",
        "max_users",
        "payment_failed",
        "subtypes",
        "wikidata_id",
        "city",
        "state",
        "country",
        "parent",
        "members",
    )
    readonly_fields = (
        "uuid",
        "slug",
        "max_users",
        "created_at",
        "updated_at",
        "individual",
    )
    autocomplete_fields = ("members", "parent", "subtypes")
    save_on_top = True
    inlines = (
        ChildrenInline,
        MembershipsInline,
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


def make_metadata_filter(field):
    """Make a dynamic filter class"""

    class MetadataFilter(admin.SimpleListFilter):
        title = field
        parameter_name = field

        def lookups(self, request, model_admin):
            return [
                (v, v)
                for v in Charge.objects.order_by()
                .values_list(f"metadata__{field}", flat=True)
                .exclude(**{f"metadata__{field}": None})
                .distinct()
            ]

        def queryset(self, request, queryset):

            if self.value():
                return queryset.filter(**{f"metadata__{field}": self.value()})

            return queryset

    return MetadataFilter


@admin.register(Charge)
class ChargeAdmin(VersionAdmin):
    list_display = ("organization", "amount", "created_at", "description")
    list_select_related = ("organization",)
    search_fields = ("organization__name", "description")
    date_hierarchy = "created_at"
    readonly_fields = ("organization", "amount", "created_at", "charge_id")
    actions = ["export_as_csv"]
    list_filter = [
        "organization__individual",
        make_metadata_filter("action"),
        make_metadata_filter("plan"),
    ]

    def export_as_csv(self, request, queryset):
        """Export charges"""

        meta = self.model._meta
        field_names = [
            "amount",
            "fee_amount",
            "organization",
            "created_at",
            "charge_id",
            "description",
        ]
        other_fields = [
            ("organization_id", lambda x: x.organization.uuid),
            (
                "type",
                lambda x: "individual" if x.organization.individual else "organization",
            ),
        ]
        metadata_fields = ["action", "plan"]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f"attachment; filename={meta}.csv"
        writer = csv.writer(response)

        headers = field_names + [n for n, _ in other_fields] + metadata_fields
        writer.writerow(headers)
        for obj in queryset:
            writer.writerow(
                [getattr(obj, field) for field in field_names]
                + [func(obj) for _, func in other_fields]
                + [obj.metadata.get(field) for field in metadata_fields]
            )

        return response

    export_as_csv.short_description = "Export Selected"


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
        "credit_card",
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


@admin.register(OrganizationSubtype)
class OrganizationSubtypeAdmin(VersionAdmin):
    list_display = ("name", "type")
    search_fields = ("name", "type__name")
