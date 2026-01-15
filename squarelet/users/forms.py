# Django
from django import forms
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging

# Third Party
import stripe
from allauth.account import forms as allauth
from allauth.account.utils import setup_user_email
from allauth.mfa.base import forms as mfa
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Layout
from psycopg2 import errors
from psycopg2.errorcodes import UNIQUE_VIOLATION

# Squarelet
from squarelet.core.forms import AvatarWidget, StripeForm
from squarelet.core.layout import Field
from squarelet.core.utils import format_stripe_error
from squarelet.organizations.models import Plan
from squarelet.organizations.models.organization import Organization
from squarelet.users.models import User

logger = logging.getLogger(__name__)


class SignupForm(allauth.SignupForm):
    """Add a name field to the sign up form"""

    name = forms.CharField(
        label=_("Full name"),
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Full name"}),
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

    tos = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(),
        label="Terms of service",
        help_text="You must agree to MuckRock's terms of service",
    )

    def __init__(self, *args, **kwargs):
        # Extract request from kwargs if present
        self.request = kwargs.pop("request", None)

        # set free to blank in case people have old links
        if "data" in kwargs and kwargs["data"].get("plan") == "free":
            data = kwargs["data"].copy()
            data["plan"] = ""
            kwargs["data"] = data
        super().__init__(*args, **kwargs)

        # set the plan field using the value in GET
        if self.request and "plan" in self.request.GET:
            plan_slug = self.request.GET.get("plan")
            try:
                plan = Plan.objects.filter(public=True).get(slug=plan_slug)
                self.initial["plan"] = plan.slug
            except Plan.DoesNotExist:
                pass

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("name"),
            Field("username"),
            Field("email", type="email"),
            Field("password1", type="password", css_class="_cls-passwordInput"),
            Field("tos", type="checkbox"),
        )
        self.fields["username"].widget.attrs.pop("autofocus", None)
        self.helper.form_tag = False
        self.fields["username"].widget.attrs["placeholder"] = ""
        self.fields["username"].help_text = _(
            "Your username must be unique; it may appear in URLs."
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
        return data

    @transaction.atomic()
    def save(self, request, setup_email=True):

        user_data = {
            "source": request.GET.get("intent", "squarelet").lower().strip()[:255]
        }
        user_data.update(self.cleaned_data)

        user = User.objects.register_user(user_data)

        plan = self.cleaned_data.get("plan")
        # Save the plan in session storage for future onboarding step #267
        if plan and plan.requires_payment():
            request.session["plan"] = plan.slug

        if setup_email:
            setup_user_email(request, user, [])

        return user


class LoginForm(allauth.LoginForm):
    """Customize the login form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["login"].widget.attrs["placeholder"] = ""
        self.fields["login"].widget.attrs.pop("autofocus", None)
        self.fields["password"].widget.attrs["placeholder"] = ""


class NewOrganizationModelChoiceField(forms.ModelChoiceField):
    """Custom ModelChoiceField to allow creating a new organization"""

    def to_python(self, value):
        if value == "new":
            return value
        return super().to_python(value)

    def validate(self, value):
        if value == "new":
            return
        super().validate(value)


class PremiumSubscriptionForm(StripeForm):
    """Create a subscription form for premium plans"""

    organization = NewOrganizationModelChoiceField(
        label=_("Select an organization"),
        queryset=None,  # Will be set in __init__
        required=True,
    )

    new_organization_name = forms.CharField(
        label=_("Name your new organization"),
        required=False,
        max_length=100,
        widget=forms.TextInput(),
    )

    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.filter(slug__in=["organization", "professional"]),
        empty_label=None,
        required=True,
    )

    receipt_emails = forms.CharField(
        label=_("Send receipts to"),
        widget=forms.TextInput(),
        required=False,
        help_text=_("Separate multiple emails with commas"),
    )

    def __init__(self, *args, plan=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stripe_token"].required = False

        if user and not user.is_anonymous:
            # Set default email for receipt_emails
            self.fields["receipt_emails"].initial = user.email
            # Filter for organizations where the user
            # is an admin or their individual organization
            self.fields["organization"].queryset = Organization.objects.filter(
                Q(memberships__user=user, memberships__admin=True)
                | Q(pk=user.individual_organization.pk)
            ).distinct()
        else:
            self.fields["organization"].queryset = Organization.objects.none()

        # Set the plan if provided
        if plan is not None:
            self.fields["plan"].initial = plan
            self.fields["plan"].queryset = Plan.objects.filter(pk=plan.pk)
            self.fields["plan"].widget = forms.HiddenInput()
            if plan.slug == "professional":
                self.fields["organization"].initial = user.individual_organization
                self.fields["organization"].disabled = True
                self.fields["organization"].widget = forms.HiddenInput()

    def clean_receipt_emails(self):
        """Make sure each line is a valid email"""
        emails = self.cleaned_data["receipt_emails"].split(",")
        emails = [e.strip() for e in emails if e.strip()]
        bad_emails = []
        for email in emails:
            try:
                validate_email(email.strip())
            except forms.ValidationError:
                bad_emails.append(email)
        if bad_emails:
            bad_emails_str = ", ".join(bad_emails)
            raise forms.ValidationError(f"Invalid email: {bad_emails_str}")
        return emails

    def clean(self):
        data = super().clean()
        stripe_token = data.get("stripe_token")
        if not stripe_token:
            self.add_error(
                "stripe_token",
                _("Payment information is missing"),
            )
        organization = data.get("organization")
        new_organization_name = data.get("new_organization_name")
        # If "new" is selected, require a name
        if organization == "new" and not new_organization_name:
            self.add_error(
                "new_organization_name",
                _("Please provide a name for the new organization"),
            )

        return data

    def save(self, user):
        """Create a subscription for the organization with the selected plan"""
        cleaned_data = self.cleaned_data
        plan: Plan = cleaned_data["plan"]
        organization: Organization = cleaned_data["organization"]
        new_organization_name = cleaned_data.get("new_organization_name")
        receipt_emails = cleaned_data.get("receipt_emails")
        stripe_token = cleaned_data.get("stripe_token")
        # When the data is submitted, no matter how the form was initialized:
        # - the plan will be either "professional" or "organization"
        # - the org will either be the user's individual org, an existing group org,
        #   or a new group org
        # - the stripe_token will be for the user's payment method
        if organization == "new" and new_organization_name:
            # Create a new organization
            organization = Organization.objects.create(
                name=new_organization_name,
                private=False,
            )
            # Add the user as an admin
            organization.add_creator(user)
            # Add receipt emails to the organization
            if receipt_emails:
                for email in receipt_emails:
                    # Check if email is already a receipt email for this organization
                    if not organization.receipt_emails.filter(email=email).exists():
                        organization.receipt_emails.create(email=email)
        try:
            organization.set_subscription(stripe_token, plan, plan.minimum_users, user)
            return True
        except stripe.error.StripeError as exc:
            user_message = format_stripe_error(exc)
            self.add_error(None, user_message)
            return False
        except errors.lookup(UNIQUE_VIOLATION) as exc:
            # Organizations can only have one subscription
            logger.error("Error creating subscription: %s", exc)
            self.add_error(None, _("This organization already has a subscription."))
            return False


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


class ResetPasswordKeyForm(mfa.BaseAuthenticateForm, allauth.ResetPasswordKeyForm):
    """Customize the reset password key form layout"""

    def __init__(self, *args, **kwargs):
        # save user here as it can be overridden in the parent class
        user = kwargs["user"]
        mfa_enabled = user.has_mfa_enabled
        super().__init__(*args, **kwargs)
        # restore user here
        self.user = user

        # remove the code field if 2FA is not enabled
        if not mfa_enabled:
            self.fields.pop("code")

        self.helper = FormHelper()
        fields = [
            Field("password1", type="password", css_class="_cls-passwordInput"),
            Field("password2", type="password", css_class="_cls-passwordInput"),
        ]
        if mfa_enabled:
            fields.extend(
                [
                    HTML(
                        "<p>Your account is protected by two-factor authentication. "
                        "Please enter an authenticator code:</p>"
                    ),
                    Field("code", type="text"),
                ]
            )

        self.helper.layout = Layout(*fields)
        self.helper.form_tag = False


class UserUpdateForm(forms.ModelForm):
    """Form for updating basic user profile information.

    Provides control over labels, help texts, placeholders, and widgets
    for the user profile edit view.
    """

    class Meta:
        model = User
        fields = ["name", "username", "avatar", "bio"]
        labels = {
            "name": _("Full Name"),
            "username": _("Username"),
            "avatar": _("Avatar"),
            "bio": _("Personal Bio"),
        }
        help_texts = {
            "name": _(
                "Your full name will be displayed on your profile "
                "and used to identify you within organizations."
            ),
            "username": _(
                "Your username must be unique; it will be used in URLs. "
                "Max. 150 characters. Only numbers, letters, periods, "
                "hyphens, and underscores are allowed."
            ),
            "avatar": _(
                "Your avatar will represent you on your profile, "
                "on public pages, and in lists."
            ),
            "bio": _("Markdown formatting supported. Maximum 250 characters."),
        }
        widgets = {
            "avatar": AvatarWidget(),
            "bio": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": _("Tell people a little about you..."),
                }
            ),
        }

    def __init__(self, *args, request=None, **kwargs):  # request optional for future
        self.request = request
        super().__init__(*args, **kwargs)

        # Customize widgets / attributes
        self.fields["name"].required = True
        self.fields["username"].required = True

        # Set autocomplete attributes
        self.fields["name"].widget.attrs.update({"autocomplete": "name"})
        self.fields["username"].widget.attrs.update({"autocomplete": "username"})
        self.fields["avatar"].widget.attrs.update({"autocomplete": "photo"})

        # Disable username field if user can no longer change it
        user_instance = self.instance
        if user_instance and hasattr(user_instance, "can_change_username"):
            if not getattr(user_instance, "can_change_username", True):
                self.fields["username"].disabled = True

    def clean_username(self):
        """Ensure username cannot be changed more than once.

        If the stored instance indicates the username can no longer
        be changed and the submitted value differs, raise a validation error.
        """
        username = self.cleaned_data.get("username")
        can_change_username = (
            self.instance
            and hasattr(self.instance, "can_change_username")
            and getattr(self.instance, "can_change_username")
        )
        is_new_username = username != self.instance.username if self.instance else False
        if can_change_username or not is_new_username:
            return username
        raise forms.ValidationError(
            _(
                "You have already changed your username "
                "once and cannot change it again."
            )
        )


class UserAutologinPreferenceForm(forms.ModelForm):
    """Simple form to allow a user to opt in/out of autologin links.

    Exposes only the ``use_autologin`` boolean from the ``User`` model so it can
    be rendered independently on a settings/privacy page without the rest of
    the profile fields.
    """

    class Meta:
        model = User
        fields = ["use_autologin"]
        labels = {
            "use_autologin": _("Use automatic login links"),
        }
        help_texts = {
            "use_autologin": _(
                "If enabled, links we email you (like notifications and password "
                "resets) will include a secure token that logs you in automatically. "
                "Disable this if you prefer to always enter your password."
            )
        }
        widgets = {"use_autologin": forms.CheckboxInput()}
