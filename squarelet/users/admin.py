# Django
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

# Third Party
from allauth.account.utils import setup_user_email, sync_user_email_addresses
from reversion.admin import VersionAdmin

# Squarelet
from squarelet.organizations.models import Organization

# Local
from .models import User


class MyUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


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
                    "org_link",
                    "can_change_username",
                )
            },
        ),
        (_("Personal info"), {"fields": ("name", "email", "email_failed")}),
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
    readonly_fields = ("uuid", "org_link", "created_at", "updated_at")
    list_display = (
        "username",
        "name",
        "email",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    search_fields = ("username", "name", "email")

    def save_model(self, request, obj, form, change):
        """Sync all auth email addresses"""
        if change:
            super().save_model(request, obj, form, change)
            sync_user_email_addresses(obj)
        else:
            Organization.objects.create_individual(obj)
            setup_user_email(request, obj, [])

    @mark_safe
    def org_link(self, obj):
        """Link to the individual org"""
        link = reverse(
            "admin:organizations_organization_change",
            args=(obj.individual_organization.pk,),
        )
        return '<a href="%s">%s</a>' % (link, obj.individual_organization.name)

    org_link.short_description = "Individual Organization"
