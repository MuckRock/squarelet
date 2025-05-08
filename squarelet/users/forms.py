# Django
from hmac import new
from operator import is_
from django import forms
from django.contrib import messages
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging

# Third Party
from allauth.account import forms as allauth
from allauth.account.utils import setup_user_email
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from psycopg2.errors import UniqueViolation
import stripe

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.core.layout import Field
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

    def __init__(self, *args, **kwargs):
        # Extract request from kwargs if present
        self.request = kwargs.pop('request', None)

        # set free to blank in case people have old links
        if "data" in kwargs and kwargs["data"].get("plan") == "free":
            data = kwargs["data"].copy()
            data["plan"] = ""
            kwargs["data"] = data
        super().__init__(*args, **kwargs)

        # set the plan field using the value in GET
        if self.request and 'plan' in self.request.GET:
            plan_slug = self.request.GET.get("plan")
            try:
                plan = Plan.objects.filter(public=True).get(slug=plan_slug)
                self.initial['plan'] = plan.slug
            except Plan.DoesNotExist:
                pass

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
        return data

    @transaction.atomic()
    def save(self, request):

        user_data = {
            "source": request.GET.get("intent", "squarelet").lower().strip()[:255]
        }
        user_data.update(self.cleaned_data)

        user = User.objects.register_user(user_data)

        plan = self.cleaned_data.get("plan")
        # Save the plan in session storage for future onboarding step #267
        if plan and plan.requires_payment():
            request.session["plan"] = plan.slug

        setup_user_email(request, user, [])

        return user


class LoginForm(allauth.LoginForm):
    """Customize the login form layout"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["login"].widget.attrs["placeholder"] = ""
        self.fields["login"].widget.attrs.pop("autofocus", None)
        self.fields["password"].widget.attrs["placeholder"] = ""


class PremiumSubscriptionForm(StripeForm):
    """Create a subscription form for premium plans"""
    # TODO: Support creating a new organization
    
    organization = forms.ModelChoiceField(
        label=_("Select an organization"),
        queryset=None,  # Will be set in __init__
        required=False,
    )

    new_organization_name = forms.CharField(
        label=_("Name your new organization"),
        required=False,
        max_length=100,
        widget=forms.TextInput(),
    )
    
    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.all(),
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
        self.fields['stripe_token'].required = False

        if user and not user.is_anonymous:
            # Set default email for receipt_emails
            self.fields['receipt_emails'].initial = user.email
            # Filter for organizations where the user is an admin or their individual organization
            self.fields['organization'].queryset = Organization.objects.filter(
                Q(memberships__user=user, memberships__admin=True) | 
                Q(pk=user.individual_organization.pk)
            ).distinct()
        else:
            self.fields['organization'].queryset = Organization.objects.none()

        # Set the plan if provided
        if plan is not None:
            self.fields['plan'].initial = plan
            self.fields['plan'].queryset = Plan.objects.filter(pk=plan.pk)
            self.fields['plan'].widget = forms.HiddenInput()
            if plan.slug == "professional":
                self.fields['organization'].initial = user.individual_organization
                self.fields['organization'].disabled = True
                self.fields['organization'].widget = forms.HiddenInput()

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
        plan = data.get('plan')
        if not plan:
            self.add_error(
                "plan",
                _("A plan is required"),
            )
        stripe_token = data.get('stripe_token')
        if not stripe_token:
            self.add_error(
                "stripe_token",
                _("Payment information is missing"),
            )
        organization = data.get('organization')
        new_organization_name = data.get('new_organization_name')
        # If "new" is selected, require a name
        if organization == 'new' and not new_organization_name:
            self.add_error('new_organization_name', _("Please provide a name for the new organization"))
        
        return data
    
    def save(self, user):
        """Create a subscription for the organization with the selected plan"""
        cleaned_data = self.cleaned_data
        plan: Plan | None = cleaned_data.get('plan')
        organization: Organization | None = cleaned_data.get('organization')
        new_organization_name = cleaned_data.get('new_organization_name')
        receipt_emails = cleaned_data.get('receipt_emails')
        stripe_token = cleaned_data.get('stripe_token')
        # When the data is submitted, no matter how the form was initialized:
        # - the plan will be either "professional" or "organization"
        # - the org will either be the user's individual org, an existing group org,
        #   or a new group org
        # - the stripe_token will be for the user's payment method
        if organization == 'new' and new_organization_name:
            # Create a new organization
            organization = Organization.objects.create(
                name=new_organization_name,
                private=True,
                owner=user,
            )
            # Add the user as an admin
            organization.add_creator(user)
            # Add receipt emails to the organization
            if receipt_emails:
                for email in receipt_emails:
                    organization.receipt_emails.create(email=email)
        try:
            if organization is not None:
                organization.create_subscription(stripe_token, plan, user)
        except stripe.error.StripeError as exc:
            logger.error("Error updating subscription: %s", exc)
            raise forms.ValidationError(
                _("Error processing payment. Please try again or contact support.")
            )
        except UniqueViolation as exc:
            # Organizations can only have one subscription
            logger.error("Error creating subscription: %s", exc)
            raise forms.ValidationError(
                _("This organization already has a subscription.")
            )


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
