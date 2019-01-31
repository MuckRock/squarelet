# Django
from django import forms
from django.db import transaction
from django.utils.translation import ugettext_lazy as _

# Third Party
from allauth.account.forms import (
    LoginForm as AllauthLoginForm,
    SignupForm as AllauthSignupForm,
)

# Crispy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.organizations.models import Organization, Plan


class SignupForm(AllauthSignupForm, StripeForm):
    """Add a name field to the sign up form"""

    name = forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"placeholder": "Full name"})
    )

    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.filter(public=True),
        empty_label=None,
        to_field_name="slug",
    )
    # XXX ensure org name is unique
    organization_name = forms.CharField(max_length=255, required=False)
    # XXX set max users?

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stripe_token"].required = False

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field(
                "name",
                css_class="_cls-nameInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
            Field(
                "username",
                css_class="_cls-usernameInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
            Field(
                "email",
                type="email",
                css_class="_cls-emailInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
            Field(
                "password1",
                type="password",
                css_class="_cls-passwordInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
        )
        self.fields["username"].widget.attrs.pop("autofocus", None)
        self.helper.form_tag = False

    def clean(self):
        data = super().clean()
        if not data["plan"].free() and not data.get("stripe_token"):
            self.add_error(
                "plan",
                _("You must supply a credit card number to upgrade to a non-free plan"),
            )
        if not data["plan"].for_individuals and not data.get("organization_name"):
            self.add_error(
                "organization_name",
                _(
                    "Organization name is required if registering an "
                    "organizational account"
                ),
            )

    @transaction.atomic()
    def save(self, request):
        user = super().save(request)
        user.name = self.cleaned_data.get("name", "")
        user.save()
        free_plan = Plan.objects.get(slug="free")
        # XXX validate things here - ie ensure name uniqueness
        individual_organization = Organization.objects.create(
            id=user.pk,
            name=user.username,
            individual=True,
            private=True,
            max_users=1,
            plan=free_plan,
            next_plan=free_plan,
        )
        individual_organization.add_creator(user)

        plan = self.cleaned_data["plan"]
        if not plan.free() and plan.for_individuals:
            individual_organization.set_subscription(
                self.cleaned_data.get("stripe_token"), plan, max_users=1
            )

        if not plan.free() and plan.for_groups:
            group_organization = Organization.objects.create(
                name=self.cleaned_data["organization_name"],
                plan=free_plan,
                next_plan=free_plan,
            )
            group_organization.add_creator(user)
            group_organization.set_subscription(
                self.cleaned_data.get("stripe_token"), plan, max_users=5
            )
        return user


class LoginForm(AllauthLoginForm):
    """Add a name field to the sign up form"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field(
                "login",
                css_class="_cls-usernameInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
            Field(
                "password",
                type="password",
                css_class="_cls-passwordInput",
                wrapper_class="_cls-field",
                template="account/field.html",
            ),
        )
        self.fields["login"].widget.attrs.pop("autofocus", None)
        self.helper.form_tag = False
