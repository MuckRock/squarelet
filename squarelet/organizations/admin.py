# Django
from django.contrib import admin

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
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "individual", "private")
    list_filter = ("plan", "individual", "private")
    list_select_related = ("plan",)
    search_fields = ("name",)
    inlines = (MembershipInline, ReceiptEmailInline, InvitationInline)

    def save_model(self, request, obj, form, change):
        """Update the stripe subscription"""
        # XXX dont set non-free plans through admin
        obj.set_subscription(
            token=None,
            plan=form.cleaned_data["plan"],
            max_users=form.cleaned_data.get("max_users"),
        )
        super().save_model(request, obj, form, change)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
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
