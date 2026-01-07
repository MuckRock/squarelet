# Django
from django.contrib import admin, messages
from django.db.models import Count, JSONField, Q, Sum
from django.forms.models import BaseInlineFormSet
from django.forms.widgets import Textarea
from django.http.response import HttpResponse
from django.urls import reverse
from django.utils.safestring import mark_safe

# Standard Library
import csv
import json
import logging
import sys
from datetime import date

# Third Party
import stripe
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.core.utils import get_stripe_dashboard_url
from squarelet.organizations.models import (
    Charge,
    Customer,
    Entitlement,
    Invitation,
    Invoice,
    Membership,
    Organization,
    OrganizationChangeLog,
    OrganizationEmailDomain,
    OrganizationInvitation,
    OrganizationSubtype,
    OrganizationType,
    OrganizationUrl,
    Plan,
    ReceiptEmail,
    Subscription,
)
from squarelet.users.models import User

logger = logging.getLogger(__name__)


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
        "invoice_link",
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
    def invoice_link(self, obj):
        """Link to the invoice's detail page in Django admin"""
        if obj.pk:
            url = reverse("admin:organizations_invoice_change", args=[obj.pk])
            return f'<a href="{url}">{obj.invoice_id}</a>'
        return obj.invoice_id or "-"

    invoice_link.short_description = "Invoice ID"

    @mark_safe
    def stripe_link(self, obj):
        """Link to Stripe invoice dashboard"""
        if obj.invoice_id:
            url = get_stripe_dashboard_url("invoices", obj.invoice_id)
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


<<<<<<< HEAD
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


||||||| parent of c91e084d (Add organization collective invitation model)
=======
class OutgoingOrganizationInvitationInline(admin.TabularInline):
    model = OrganizationInvitation
    fk_name = "from_organization"
    fields = (
        "to_organization",
        "relationship_type",
        "request",
        "accepted_at",
        "rejected_at",
    )
    readonly_fields = ("to_organization", "accepted_at", "rejected_at")
    extra = 0
    verbose_name = "Outgoing Organization Invitation"
    verbose_name_plural = "Outgoing Organization Invitations"


class IncomingOrganizationInvitationInline(admin.TabularInline):
    model = OrganizationInvitation
    fk_name = "to_organization"
    fields = (
        "from_organization",
        "relationship_type",
        "request",
        "accepted_at",
        "rejected_at",
    )
    readonly_fields = ("from_organization", "accepted_at", "rejected_at")
    extra = 0
    verbose_name = "Incoming Organization Invitation"
    verbose_name_plural = "Incoming Organization Invitations"


>>>>>>> c91e084d (Add organization collective invitation model)
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
        "collective_enabled",
        "share_resources",
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
        OutgoingOrganizationInvitationInline,
        IncomingOrganizationInvitationInline,
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
        """Add user link for individual organizations"""
        base_readonly = self.readonly_fields
        if obj and obj.individual:
            return ("user_link",) + base_readonly
        else:
            return base_readonly

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
<<<<<<< HEAD


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
        "hosted_invoice_url_link",
    )
    fields = (
        "invoice_id",
        "stripe_link",
        "hosted_invoice_url_link",
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
    actions = ["mark_as_paid"]

    def get_readonly_fields(self, request, obj=None):
        """Make all fields readonly when editing existing invoice"""
        if obj:  # Editing existing invoice
            # Return all fields as readonly
            readonly = [
                "get_amount",
                "updated_at",
                "stripe_link",
                "hosted_invoice_url_link",
                "invoice_id",
                "organization",
                "subscription",
                "amount",
                "status",
                "due_date",
                "last_overdue_email_sent",
                "created_at",
            ]
            return tuple(readonly)
        # When creating new invoice, only standard readonly fields
        return (
            "get_amount",
            "updated_at",
            "stripe_link",
            "hosted_invoice_url_link",
        )

    @mark_safe
    def stripe_link(self, obj):
        """Link to Stripe invoice dashboard"""
        if obj.invoice_id:
            url = get_stripe_dashboard_url("invoices", obj.invoice_id)
            return f'<a href="{url}" target="_blank">View in Stripe</a>'
        return "-"

    stripe_link.short_description = "Stripe Dashboard"

    @mark_safe
    def hosted_invoice_url_link(self, obj):
        """Link to customer-facing hosted invoice page"""
        if obj.invoice_id:
            url = obj.get_hosted_invoice_url()
            if url:
                return f'<a href="{url}" target="_blank">Customer Payment Page</a>'
            return "Not available"
        return "-"

    hosted_invoice_url_link.short_description = "Hosted Invoice URL"

    def get_amount(self, obj):
        return f"${obj.amount_dollars:.2f}"

    get_amount.short_description = "Amount"

    def mark_as_paid(self, request, queryset):
        """Mark selected invoices as paid and sync to Stripe"""
        success_count = 0
        error_count = 0

        for invoice in queryset.filter(status="open"):
            try:
                # Retrieve invoice from Stripe and call pay() on it
                stripe_invoice = stripe.Invoice.retrieve(invoice.invoice_id)
                stripe_invoice.pay(paid_out_of_band=True)
                # Update local DB after Stripe succeeds
                invoice.status = "paid"
                invoice.save()
                success_count += 1
            except stripe.error.StripeError as exc:
                logger.error(
                    "Failed to mark invoice %s as paid in Stripe: %s",
                    invoice.invoice_id,
                    exc,
                    exc_info=sys.exc_info(),
                )
                error_count += 1

        if success_count > 0:
            self.message_user(
                request,
                f"{success_count} invoice(s) marked as paid.",
            )
        if error_count > 0:
            self.message_user(
                request,
                f"{error_count} invoice(s) could not be updated in Stripe. "
                "Check logs for errors.",
                level=messages.ERROR,
            )

    mark_as_paid.short_description = "Mark as Paid"

    def changelist_view(self, request, extra_context=None):
        """Handle custom single-invoice actions"""
        # Check if this is a mark_as_paid_single action
        if request.GET.get("action") == "mark_as_paid_single":
            invoice_id = request.GET.get("invoice_id")
            if invoice_id:
                try:
                    # Verify invoice exists before processing
                    Invoice.objects.get(pk=invoice_id)
                    # Call mark_as_paid with a queryset containing just this invoice
                    queryset = Invoice.objects.filter(pk=invoice_id)
                    self.mark_as_paid(request, queryset)
                    # Redirect to the invoice detail page
                    return HttpResponse(
                        status=302,
                        headers={
                            "Location": reverse(
                                "admin:organizations_invoice_change", args=[invoice_id]
                            )
                        },
                    )
                except Invoice.DoesNotExist:
                    self.message_user(
                        request, "Invoice not found.", level=messages.ERROR
                    )

        return super().changelist_view(request, extra_context)
||||||| parent of c91e084d (Add organization collective invitation model)
=======


@admin.register(OrganizationInvitation)
class OrganizationInvitationAdmin(VersionAdmin):
    list_display = (
        "from_organization",
        "to_organization",
        "from_user",
        "closed_by_user",
        "relationship_type",
        "request",
        "created_at",
        "accepted_at",
        "rejected_at",
    )
    list_filter = ("relationship_type", "request")
    search_fields = ("from_organization__name", "to_organization__name")
    readonly_fields = ("uuid", "created_at", "accepted_at", "rejected_at")
    autocomplete_fields = (
        "from_organization",
        "to_organization",
        "from_user",
        "closed_by_user",
    )
    date_hierarchy = "created_at"
>>>>>>> c91e084d (Add organization collective invitation model)
