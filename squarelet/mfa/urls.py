"""Custom MFA URL configuration to use views that redirect to user detail page."""

# Django
from django.urls import path

# Local
from . import views

app_name = "mfa"

urlpatterns = [
    # TOTP URLs
    path("totp/activate/", views.activate_totp, name="mfa_activate_totp"),
    path("totp/deactivate/", views.deactivate_totp, name="mfa_deactivate_totp"),
    # Recovery codes URLs
    path(
        "recovery-codes/generate/",
        views.generate_recovery_codes,
        name="mfa_generate_recovery_codes",
    ),
    # WebAuthn URLs
    path("webauthn/add/", views.add_webauthn, name="mfa_add_webauthn"),
    path(
        "webauthn/<int:pk>/remove/",
        views.remove_webauthn,
        name="mfa_remove_webauthn",
    ),
    path(
        "webauthn/<int:pk>/edit/",
        views.edit_webauthn,
        name="mfa_edit_webauthn",
    ),
]
