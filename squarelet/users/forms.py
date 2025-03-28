# Django
from django import forms
from django.contrib import messages
from django.db import transaction
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging

# Third Party
from allauth.account import forms as allauth
from allauth.account.utils import setup_user_email
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout

# Squarelet
from squarelet.core.layout import Field
from squarelet.organizations.models import Plan
from squarelet.users.models import User

logger = logging.getLogger(__name__)


class SignupForm(allauth.SignupForm):
    """Add a name field to the sign up form"""

    name = forms.CharField(
        label=_("Full name"), max_length=255, widget=forms.TextInput(attrs={"placeholder": "Full name"})
    )

    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.filter(public=True),
        empty_label=None,
        to_field_name="slug",
        widget=forms.HiddenInput(),
        required=False,
    )
    organization_name = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        # set free to blank in case people have old links
        if "data" in kwargs and kwargs["data"].get("plan") == "free":
            data = kwargs["data"].copy()
            data["plan"] = ""
            kwargs["data"] = data
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("name"),
            Field("username"),
            Field("email", type="email"),
            Field("password1", type="password", css_class="_cls-passwordInput"),
        )
        self.fields["username"].widget.attrs.pop("autofocus", None)
        self.helper.form_tag = False
        self.fields["username"].widget.attrs["placeholder"] = ""
        self.fields["username"].help_text = _(
            "Your username must be unique; it will be used in URLs."
        )
        self.fields["name"].widget.attrs["placeholder"] = ""
        self.fields["name"].help_text = _(
            """Your full name will be displayed on your profile
            and used to identify you within organizations."""
        )
        self.fields["email"].widget.attrs["placeholder"] = ""
        self.fields["password1"].widget.attrs["placeholder"] = ""

    def clean(self):
        data = super().clean()
        if self.errors:
            log_data = self.data.copy()
            log_data.pop("password1", None)
            logger.warning("Failed signup attempt:\n\t%r\n\t%s", self.errors, log_data)
        plan = data.get("plan")
        # Save the plan in session storage for future onboarding step #267
        if plan and plan.requires_payment():
            self.request.session["plan"] = plan.slug
        return data

    @transaction.atomic()
    def save(self, request):

        user_data = {
            "source": request.GET.get("intent", "squarelet").lower().strip()[:13]
        }
        user_data.update(self.cleaned_data)

        user, _, error = User.objects.register_user(user_data)

        setup_user_email(request, user, [])

        if error:
            messages.error(request, error)

        return user


class LoginForm(allauth.LoginForm):
    """Customize the login form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["login"].widget.attrs["placeholder"] = ""
        self.fields["login"].widget.attrs.pop("autofocus", None)
        self.fields["password"].widget.attrs["placeholder"] = ""


class AddEmailForm(allauth.AddEmailForm):
    """Customize the add email form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(Field("email", type="email"))
        self.helper.form_tag = False


class ChangePasswordForm(allauth.ChangePasswordForm):
    """Customize the change password form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("oldpassword", type="password", css_class="_cls-passwordInput"),
            Field("password1", type="password", css_class="_cls-passwordInput"),
            Field("password2", type="password", css_class="_cls-passwordInput"),
        )
        self.helper.form_tag = False


class SetPasswordForm(allauth.SetPasswordForm):
    """Customize the set password form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("password1", type="password", css_class="_cls-passwordInput"),
            Field("password2", type="password", css_class="_cls-passwordInput"),
        )
        self.helper.form_tag = False


class ResetPasswordForm(allauth.ResetPasswordForm):
    """Customize the reset password form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(Field("email", type="email"))
        self.helper.form_tag = False


class ResetPasswordKeyForm(allauth.ResetPasswordKeyForm):
    """Customize the reset password key form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("password1", type="password", css_class="_cls-passwordInput"),
            Field("password2", type="password", css_class="_cls-passwordInput"),
        )
        self.helper.form_tag = False
