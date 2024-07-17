# Django
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.postgres.aggregates.general import StringAgg
from django.db.models.expressions import Exists, OuterRef
from django.db.models.functions.comparison import Collate
from django.http.response import HttpResponse
from django.urls import reverse
from django.urls.conf import re_path
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

# Standard Library
import csv

# Third Party
from allauth.account.models import EmailAddress
from allauth.account.utils import setup_user_email, sync_user_email_addresses
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import Invitation, Organization

# Local
from .models import User


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
                )
            },
        ),
        (_("Personal info"), {"fields": ("name", "email", "email_failed", "bio")}),
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
        (_("Important dates"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = (
        "uuid",
        "individual_org_link",
        "all_org_links",
        "created_at",
        "updated_at",
    )
    list_display = (
        "username",
        "name",
        "email",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    search_fields = ("username_deterministic", "name", "email_deterministic")
    inlines = [EmailInline, InvitationInline]

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

    def save_model(self, request, obj, form, change):
        """Sync all auth email addresses"""
        if change:
            super().save_model(request, obj, form, change)
            sync_user_email_addresses(obj)
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
