# Django
from django.contrib import admin
from django.db.models import Count, JSONField, Q, Sum
from django.forms.models import BaseInlineFormSet
from django.forms.widgets import Textarea
from django.http.response import HttpResponse
from django.urls import reverse
from django.utils.safestring import mark_safe

# Standard Library
import csv
import json
from datetime import date

# Third Party
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import (
    Charge,
    Customer,
    Entitlement,
    Invoice,
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


# https://stackoverflow.com/questions/48145992/showing-json-field-in-django-admin
# https://github.com/MuckRock/documentcloud/blob/master/documentcloud/addons/admin.py#L26-L38
class PrettyJSONWidget(Textarea):
    def format_value(self, value):
        try:
            # Accept Python objects and JSON strings
            if isinstance(value, (dict, list)):
                data = value
            elif value in (None, ""):
                return ""
            else:
                data = json.loads(value)

            pretty = json.dumps(data, indent=2, sort_keys=True)

            # these lines will try to adjust size of TextArea to fit to content
            row_lengths = [len(r) for r in pretty.split("\n")]
            self.attrs["rows"] = min(max(len(row_lengths) + 2, 10), 30)
            self.attrs["cols"] = min(max(max(row_lengths) + 2, 40), 120)
            return pretty
        except Exception:  # pylint: disable=broad-except
            return super().format_value(value)


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    readonly_fields = ("plan", "subscription_id", "update_on", "cancelled")
    extra = 0


class CustomerInline(admin.TabularInline):
    model = Customer
    readonly_fields = ("customer_id",)
    extra = 0


class InvoiceInline(admin.TabularInline):
    model = Invoice
    readonly_fields = (
        "invoice_id",
        "stripe_link",
        "amount_dollars",
        "status",
        "due_date",
        "created_at",
    )
    fields = readonly_fields
    extra = 0
    can_delete = False
    max_num = 0

    @mark_safe
    def stripe_link(self, obj):
        """Link to Stripe invoice dashboard"""
        if obj.invoice_id:
            url = f"https://dashboard.stripe.com/invoices/{obj.invoice_id}"
            return f'<a href="{url}" target="_blank">View in Stripe</a>'
        return "-"

    stripe_link.short_description = "Stripe"

    def amount_dollars(self, obj):
        return f"${obj.amount_dollars:.2f}"

    amount_dollars.short_description = "Amount"


class MembershipFormset(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queryset = self.queryset.select_related("user", "organization")


class MembershipInline(admin.TabularInline):
    model = Membership
    readonly_fields = ("user", "created_at")
    fields = ["user", "admin", "created_at"]
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


class OverdueInvoiceFilter(admin.SimpleListFilter):
    """Filter organizations by whether they have overdue invoices"""

    title = "overdue invoices"
    parameter_name = "has_overdue_invoices"

    def lookups(self, request, model_admin):
        return [
            ("yes", "Has overdue invoices"),
            ("no", "No overdue invoices"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                invoices__status="open", invoices__due_date__lt=date.today()
            ).distinct()
        elif self.value() == "no":
            # Organizations with no open invoices or no overdue invoices
            return queryset.exclude(
                invoices__status="open", invoices__due_date__lt=date.today()
            )
        return queryset


@admin.register(Organization)
class OrganizationAdmin(VersionAdmin):
    def export_organizations_as_csv(self, request, queryset):
        """Export selected organizations records to CSV."""
        field_names = [
            "uuid",
            "name",
            "slug",
            "individual",
            "private",
            "verified_journalist",
            "email_domains",
        ]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            "attachment; filename=accounts_organization_statistics.csv"
        )

        writer = csv.writer(response)
        writer.writerow(field_names)

        for obj in queryset:
            writer.writerow(
                [
                    obj.uuid,
                    obj.name,
                    obj.slug,
                    obj.individual,
                    obj.private,
                    obj.verified_journalist,
                    self.get_email_domains(obj),
                ]
            )

        return response

    export_organizations_as_csv.short_description = (
        "Export selected organizations to CSV"
    )

    list_display = (
        "name",
        "individual",
        "private",
        "verified_journalist",
        "get_subtypes",
        "get_outstanding_invoices",
    )
    list_filter = (
        "individual",
        "private",
        "verified_journalist",
        "hub_eligible",
        "subtypes",
        OverdueInvoiceFilter,
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
        "allow_auto_join",
        "max_users",
        "payment_failed",
        "subtypes",
        "wikidata_id",
        "city",
        "state",
        "country",
        "parent",
        "members",
        "merged",
        "merged_at",
        "merged_by",
    )
    readonly_fields = (
        "uuid",
        "slug",
        "max_users",
        "created_at",
        "updated_at",
        "individual",
        "merged",
        "merged_at",
        "merged_by",
    )
    actions = [export_organizations_as_csv]
    autocomplete_fields = ("members", "parent", "subtypes")
    save_on_top = True
    inlines = (
        ChildrenInline,
        MembershipsInline,
        OrganizationUrlInline,
        OrganizationEmailDomainInline,
        SubscriptionInline,
        CustomerInline,
        InvoiceInline,
        MembershipInline,
        ReceiptEmailInline,
        InvitationInline,
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("subtypes", "domains")
            .annotate(
                outstanding_invoice_count=Count(
                    "invoices", filter=Q(invoices__status="open")
                ),
                outstanding_invoice_total=Sum(
                    "invoices__amount", filter=Q(invoices__status="open")
                ),
            )
        )

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

    def get_email_domains(self, obj):
        return ", ".join(domain.domain for domain in obj.domains.all())

    get_email_domains.short_description = "Email Domains"

    def get_outstanding_invoices(self, obj):
        """Display count and total of outstanding invoices"""
        count = getattr(obj, "outstanding_invoice_count", 0)
        total = getattr(obj, "outstanding_invoice_total", 0)
        if count > 0:
            return f"{count} (${total / 100:.2f})"
        return "-"

    get_outstanding_invoices.short_description = "Outstanding Invoices"
    get_outstanding_invoices.admin_order_field = "outstanding_invoice_count"


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
        "slack_webhook_url",
    )
    search_fields = ("name", "description")
    autocomplete_fields = ("private_organizations", "entitlements")
    filter_horizontal = ("entitlements", "private_organizations")
    formfield_overrides = {
        JSONField: {"widget": PrettyJSONWidget},
    }


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


@admin.register(Invoice)
class InvoiceAdmin(VersionAdmin):
    list_display = (
        "invoice_id",
        "organization",
        "get_amount",
        "status",
        "due_date",
        "created_at",
    )
    list_select_related = ("organization",)
    list_filter = ("status",)
    search_fields = ("invoice_id", "organization__name")
    date_hierarchy = "created_at"
    readonly_fields = (
        "get_amount",
        "updated_at",
        "stripe_link",
    )
    fields = (
        "invoice_id",
        "stripe_link",
        "organization",
        "subscription",
        "amount",
        "get_amount",
        "status",
        "due_date",
        "last_overdue_email_sent",
        "created_at",
        "updated_at",
    )
    actions = ["mark_as_paid", "mark_as_uncollectible"]

    @mark_safe
    def stripe_link(self, obj):
        """Link to Stripe invoice dashboard"""
        if obj.invoice_id:
            url = f"https://dashboard.stripe.com/invoices/{obj.invoice_id}"
            return f'<a href="{url}" target="_blank">View in Stripe</a>'
        return "-"

    stripe_link.short_description = "Stripe Dashboard"

    def get_amount(self, obj):
        return f"${obj.amount_dollars:.2f}"

    get_amount.short_description = "Amount"

    def mark_as_paid(self, request, queryset):
        """Mark selected invoices as paid"""
        updated = queryset.filter(status="open").update(status="paid")
        self.message_user(
            request,
            f"{updated} invoice(s) marked as paid.",
        )

    mark_as_paid.short_description = "Mark as Paid"

    def mark_as_uncollectible(self, request, queryset):
        """Mark selected invoices as uncollectible"""
        updated = queryset.filter(status="open").update(status="uncollectible")
        self.message_user(
            request,
            f"{updated} invoice(s) marked as uncollectible.",
        )

    mark_as_uncollectible.short_description = "Mark as Uncollectible"
