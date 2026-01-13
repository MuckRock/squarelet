"""Custom MFA views that override allauth defaults to redirect to user detail page."""

# Django
from django.urls import reverse

# Third Party
from allauth.mfa.recovery_codes.views import (
    GenerateRecoveryCodesView as BaseGenerateRecoveryCodesView,
)
from allauth.mfa.totp.views import (
    ActivateTOTPView as BaseActivateTOTPView,
    DeactivateTOTPView as BaseDeactivateTOTPView,
)
from allauth.mfa.webauthn.views import (
    AddWebAuthnView as BaseAddWebAuthnView,
    EditWebAuthnView as BaseEditWebAuthnView,
    RemoveWebAuthnView as BaseRemoveWebAuthnView,
)


class ActivateTOTPView(BaseActivateTOTPView):
    """Override TOTP activation to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to user detail page after TOTP activation."""
        if self.did_generate_recovery_codes:
            return reverse("mfa_view_recovery_codes")
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class DeactivateTOTPView(BaseDeactivateTOTPView):
    """Override TOTP deactivation to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to user detail page after TOTP deactivation."""
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class GenerateRecoveryCodesView(BaseGenerateRecoveryCodesView):
    """Override recovery code generation to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to view recovery codes page after generation."""
        return reverse("mfa_view_recovery_codes")


class AddWebAuthnView(BaseAddWebAuthnView):
    """Override WebAuthn addition to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to user detail page after adding WebAuthn."""
        if self.did_generate_recovery_codes:
            return reverse("mfa_view_recovery_codes")
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class RemoveWebAuthnView(BaseRemoveWebAuthnView):
    """Override WebAuthn removal to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to user detail page after removing WebAuthn."""
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class EditWebAuthnView(BaseEditWebAuthnView):
    """Override WebAuthn editing to redirect to user detail page."""

    def get_success_url(self):
        """Redirect to user detail page after editing WebAuthn."""
        return reverse("users:detail", kwargs={"username": self.request.user.username})


# View instances for URL configuration
activate_totp = ActivateTOTPView.as_view()
deactivate_totp = DeactivateTOTPView.as_view()
generate_recovery_codes = GenerateRecoveryCodesView.as_view()
add_webauthn = AddWebAuthnView.as_view()
remove_webauthn = RemoveWebAuthnView.as_view()
edit_webauthn = EditWebAuthnView.as_view()
