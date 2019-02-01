# Django
# Third Party
from django import forms
from django.core.validators import validate_email
from django.utils.translation import ugettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.core.layout import Field

# Local
from .models import Plan


class UpdateForm(StripeForm):
    """Update an organization"""

    plan = forms.ModelChoiceField(
        label=_("Plan"), queryset=Plan.objects.none(), empty_label=None
    )
    max_users = forms.IntegerField(label=_("Number of Users"), min_value=5)
    private = forms.BooleanField(label=_("Private"), required=False)
    receipt_emails = forms.CharField(
        label=_("Receipt Emails"),
        widget=forms.Textarea(),
        required=False,
        help_text=_("One email address per line"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_group_options()

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("stripe_token"),
            Field("plan"),
            Field("max_users"),
            Field("private"),
            Field("receipt_emails"),
            Field("use_card_on_file"),
        )
        self.helper.form_tag = False

    def _set_group_options(self):
        # only show public options, plus the current plan, in case they are currently
        # on a private plan
        current_plan_qs = Plan.objects.filter(id=self.organization.plan_id)
        if self.organization.individual:
            self.fields["plan"].queryset = (
                Plan.objects.individual_choices() | current_plan_qs
            )
            del self.fields["max_users"]
            del self.fields["private"]
        else:
            self.fields["plan"].queryset = (
                Plan.objects.group_choices() | current_plan_qs
            )
            limit_value = max(5, self.organization.user_count())
            self.fields["max_users"].validators[0].limit_value = limit_value
            self.fields["max_users"].widget.attrs["min"] = limit_value
            self.fields["max_users"].initial = limit_value

    def clean_receipt_emails(self):
        """Make sure each line is a valid email"""
        emails = self.cleaned_data["receipt_emails"].split("\n")
        emails = [e.strip() for e in emails if e.strip()]
        bad_emails = []
        for email in emails:
            try:
                validate_email(email.strip())
            except forms.ValidationError:
                bad_emails.append(email)
        if bad_emails:
            raise forms.ValidationError("Invalid email: %s" % ", ".join(bad_emails))
        return emails

    def clean(self):
        data = super().clean()

        payment_required = data["plan"] != self.organization.plan and (
            data["plan"].base_price > 0 or data["plan"].price_per_user > 0
        )
        payment_supplied = data.get("use_card_on_file") or data.get("stripe_token")

        if payment_required and not payment_supplied:
            self.add_error(
                None,
                _("You must supply a credit card number to upgrade to a non-free plan"),
            )

        if "max_users" in data and data["max_users"] < data["plan"].minimum_users:
            self.add_error(
                "max_users",
                _(
                    "The minimum users for the {} plan is {}".format(
                        data["plan"], data["plan"].minimum_users
                    )
                ),
            )

        return data


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    email = forms.EmailField()
