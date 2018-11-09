# Django
from django import forms
from django.db import transaction
from django.utils.translation import ugettext_lazy as _

# Third Party
from allauth.account.forms import SignupForm as AllauthSignupForm

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.organizations.choices import Plan
from squarelet.organizations.models import Organization


class SignupForm(AllauthSignupForm, StripeForm):
    """Add a name field to the sign up form"""

    name = forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"placeholder": "Full name"})
    )

    # XXX js change choices to org/non org on front end
    plan = forms.TypedChoiceField(label=_("Plan"), coerce=int, choices=Plan.choices)
    # XXX ensure org name is unique
    organization_name = forms.CharField(max_length=255, required=False)
    # XXX set max users?

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stripe_token"].required = False

    def clean(self):
        data = super().clean()
        if data.get("plan") != Plan.free and not data.get("stripe_token"):
            self.add_error(
                "plan",
                _("You must supply a credit card number to upgrade to a non-free plan"),
            )
        if data.get("plan") in [Plan.basic, Plan.plus] and not data.get(
            "organization_name"
        ):
            self.add_error(
                "organization_name",
                _(
                    "Organization name is required if registering an "
                    "organizational account"
                ),
            )

    def save(self, request):
        with transaction.atomic():
            user = super().save(request)
            user.name = self.cleaned_data.get("name", "")
            # XXX validate things here - ie ensure name uniqueness
            individual_organization = Organization.objects.create(
                id=user.pk,
                name=user.username,
                individual=True,
                private=True,
                max_users=1,
            )
            individual_organization.add_creator(user)

            if self.cleaned_data.get("plan") == Plan.pro:
                individual_organization.set_subscription(
                    self.cleaned_data.get("stripe_token"),
                    self.cleaned_data.get("plan"),
                    1,
                )

            if self.cleaned_data.get("plan") in [Plan.basic, Plan.plus]:
                group_organization = Organization.objects.create(
                    name=self.cleaned_data.get("organization_name")
                )
                group_organization.add_creator(user)
                group_organization.set_subscription(
                    self.cleaned_data.get("stripe_token"),
                    self.cleaned_data.get("plan"),
                    5,
                )
            return user
