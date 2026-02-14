# Django
from django.contrib import admin
from django.contrib.admin.filters import SimpleListFilter
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Permission
from django.contrib.postgres.aggregates.general import StringAgg
from django.db.models.expressions import Exists, OuterRef
from django.db.models.functions.comparison import Collate
from django.db.models.query_utils import Q
from django.http.response import HttpResponse
from django.urls import reverse
from django.urls.conf import re_path
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

# Standard Library
import csv
import json
from itertools import chain

# Third Party
from allauth.account.models import EmailAddress
from allauth.account.utils import setup_user_email
from allauth.mfa.admin import AuthenticatorAdmin
from allauth.mfa.models import Authenticator
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import Invitation, Organization
from squarelet.organizations.models.organization import Membership

# Local
from .models import LoginLog, User


class PermissionFilter(SimpleListFilter):
    """Filter for users by permission"""

    title = "Permission"
    parameter_name = "permission"
    template = "admin/dropdown_filter.html"

    def lookups(self, request, model_admin):
        return Permission.objects.values_list("pk", "name")

    def queryset(self, request, queryset):
        return queryset.filter(
            Q(user_permissions=self.value())
            | Q(groups__permissions=self.value())
            | Q(is_superuser=True)
        ).distinct()


class EmailInline(admin.TabularInline):
    model = EmailAddress
    extra = 0
    readonly_fields = ["verified", "primary"]


class MyUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class InvitationInline(admin.TabularInline):
    model = Invitation
    readonly_fields = ("organization", "email", "request", "accepted_at", "rejected_at")
    extra = 0


class MembershipInline(admin.TabularInline):
    model = Membership
    fields = ["organization", "admin"]
    autocomplete_fields = ("organization",)
    extra = 0


@admin.register(User)
class MyUserAdmin(VersionAdmin, AuthUserAdmin):
    add_form = MyUserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "password1", "password2"),
            },
        ),
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uuid",
                    "username",
                    "password",
                    "individual_org_link",
                    "all_org_links",
                    "can_change_username",
                    "source",
                )
            },
        ),
        (
            _("Personal info"),
            {"fields": ("name", "email", "email_failed", "bio")},
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                )
            },
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "last_mfa_prompt", "created_at", "updated_at")},
        ),
    )
    superuser_fieldsets = (
        (
            None,
            {
                "fields": (
                    "uuid",
                    "username",
                    "password",
                    "individual_org_link",
                    "all_org_links",
                    "can_change_username",
                    "source",
                )
            },
        ),
        (
            _("Personal info"),
            {"fields": ("name", "email", "email_failed", "bio")},
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "last_mfa_prompt", "created_at", "updated_at")},
        ),
    )
    readonly_fields = (
        "uuid",
        "individual_org_link",
        "all_org_links",
        "created_at",
        "updated_at",
        "source",
    )
    list_display = (
        "username",
        "name",
        "email",
        "is_staff",
        "is_superuser",
        "is_active",
        "created_at",
    )
    list_filter = AuthUserAdmin.list_filter + (PermissionFilter,)
    search_fields = ("username_deterministic", "name", "email_deterministic")
    inlines = [EmailInline, InvitationInline, MembershipInline]

    def get_queryset(self, request):
        """Add deterministic fields for username and email so they
        can be searched"""
        return (
            super()
            .get_queryset(request)
            .annotate(
                email_deterministic=Collate("email", "und-x-icu"),
                username_deterministic=Collate("username", "und-x-icu"),
            )
        )

    def get_fieldsets(self, request, obj=None):
        """Remove permission settings for non-super users"""
        if request.user.is_superuser:
            return self.superuser_fieldsets
        else:
            return self.fieldsets

    def save_model(self, request, obj, form, change):
        """Sync all auth email addresses"""
        if change:
            super().save_model(request, obj, form, change)
            if (
                obj.email
                and not EmailAddress.objects.filter(user=obj, email=obj.email).exists()
            ):
                EmailAddress.objects.get_or_create(
                    user=obj,
                    email=obj.email,
                    defaults={"primary": False, "verified": False},
                )
        else:
            Organization.objects.create_individual(obj)
            setup_user_email(request, obj, [])

    @mark_safe
    def individual_org_link(self, obj):
        """Link to the individual org"""
        link = reverse(
            "admin:organizations_organization_change",
            args=(obj.individual_organization.pk,),
        )
        return f'<a href="{link}">{obj.individual_organization.name}</a>'

    individual_org_link.short_description = "Individual Organization"

    @mark_safe
    def all_org_links(self, obj):
        """Link to the user's other orgs"""
        orgs = obj.organizations.filter(individual=False)
        links = []
        for org in orgs:
            links.append(
                (
                    reverse(
                        "admin:organizations_organization_change",
                        args=(org.pk,),
                    ),
                    org.name,
                )
            )
        return ", ".join(f'<a href="{link}">{name}</a>' for link, name in links)

    all_org_links.short_description = "All Organizations"

    def get_urls(self):
        """Add custom URLs here"""
        urls = super().get_urls()
        my_urls = [
            re_path(
                r"^export/$",
                self.admin_site.admin_view(self.user_export),
                name="users-admin-user-export",
            ),
        ]
        return my_urls + urls

    def user_export(self, request):
        response = HttpResponse(
            content_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="squarelet_users.csv"'
            },
        )
        writer = csv.writer(response)

        def format_date(date):
            if date is not None:
                return date.strftime("%Y-%m-%d")
            else:
                return ""

        writer.writerow(
            [
                "username",
                "name",
                "email",
                "last_login",
                "date_joined",
                "verified",
                "orgs",
            ]
        )
        for user in (
            User.objects.only("username", "name", "email", "last_login", "created_at")
            .annotate(
                verified=Exists(
                    Organization.objects.filter(
                        verified_journalist=True, users=OuterRef("pk")
                    )
                ),
                org_names=StringAgg("organizations__name", ", "),
            )
            .iterator(chunk_size=2000)
        ):
            writer.writerow(
                [
                    user.username,
                    user.name,
                    user.email,
                    format_date(user.last_login),
                    format_date(user.created_at),
                    user.verified,
                    user.org_names,
                ]
            )

        return response


@admin.register(LoginLog)
class LoginLogAdmin(admin.ModelAdmin):
    readonly_fields = ("user", "client", "formatted_metadata", "created_at")
    fields = ("user", "client", "formatted_metadata", "created_at")
    list_display = ("user", "client", "created_at")
    date_hierarchy = "created_at"
    list_filter = ("client",)
    list_select_related = ("user", "client")
    actions = ["export_as_csv"]

    def formatted_metadata(self, obj):
        json_data = json.dumps(obj.metadata, indent=4)
        return mark_safe(f"<pre>{json_data}</pre>")

    formatted_metadata.short_description = "Metadata"

    def export_as_csv(self, request, queryset):
        """Export login logs"""

        meta = self.model._meta
        fields = [
            ("user", lambda x: x.user.username),
            ("email", lambda x: x.user.email),
            ("client", lambda x: x.client),
            ("created_at", lambda x: x.created_at),
        ]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f"attachment; filename={meta}.csv"
        writer = csv.writer(response)

        writer.writerow(name for name, _ in fields)
        for obj in queryset:
            writer.writerow(
                [func(obj) for _, func in fields]
                + list(
                    chain(
                        *[
                            [m["name"], "Free" if m["plan"] is None else m["plan"]]
                            for m in obj.metadata["organizations"]
                        ]
                    )
                )
            )

        return response

    export_as_csv.short_description = "Export Selected"


admin.site.unregister(Authenticator)


@admin.register(Authenticator)
class MyAuthenticatorAdmin(AuthenticatorAdmin):
    search_fields = ("user__username", "user__email")
