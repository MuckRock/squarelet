# Django
from django import forms
from django.core.validators import validate_email
from django.utils.translation import ugettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout

# Squarelet
from squarelet.core.forms import ImagePreviewWidget, StripeForm
from squarelet.core.layout import Field
from squarelet.organizations.choices import StripeAccounts

# Local
from .models import Organization, Plan


class PaymentForm(StripeForm):
    """Update subscription information for an organization"""

    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.none(),
        empty_label="Free",
        required=False,
    )
    max_users = forms.IntegerField(label=_("Number of Users"), min_value=5)
    receipt_emails = forms.CharField(
        label=_("Receipt Emails"),
        widget=forms.Textarea(),
        required=False,
        help_text=_("One email address per line"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_group_options()
        # stripe token is only required if switching to a paid plan
        # this is checked in the clean method
        self.fields["stripe_token"].required = False

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("stripe_pk"),
            Field("stripe_token"),
            Fieldset("Plan", Field("plan"), css_class="_cls-compactField"),
            Fieldset("Max Users", Field("max_users"), css_class="_cls-compactField")
            if "max_users" in self.fields
            else None,
            Fieldset(
                "Receipt emails",
                Field("receipt_emails", id="_id-receiptEmails"),
                css_class="_cls-resizeField",
            ),
            Fieldset(
                "Credit card",
                Field("use_card_on_file"),
                css_class="_cls-compactField",
                id="_id-cardFieldset",
            )
            if "use_card_on_file" in self.fields
            else None,
        )
        self.helper.form_tag = False

    def _set_group_options(self):
        # only show public options, plus the current plan, in case they are currently
        # on a private plan, plus private plans they have been given access to
        self.fields["plan"].queryset = Plan.objects.choices(
            self.organization, StripeAccounts.muckrock
        )
        self.fields["plan"].default = self.organization.plan
        if self.organization.individual:
            del self.fields["max_users"]
        else:
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
        plan = data.get("plan")

        payment_required = plan != self.organization.plan and (
            plan and plan.requires_payment()
        )
        payment_supplied = data.get("use_card_on_file") or data.get("stripe_token")

        if payment_required and not payment_supplied:
            self.add_error(
                None,
                _("You must supply a credit card number to upgrade to a non-free plan"),
            )

        if plan and "max_users" in data and data["max_users"] < plan.minimum_users:
            self.add_error(
                "max_users",
                _(
                    "The minimum users for the {} plan is {}".format(
                        plan, plan.minimum_users
                    )
                ),
            )

        return data


class UpdateForm(forms.ModelForm):
    """Update misc information for an organization"""

    avatar = forms.ImageField(
        label=_("Avatar"), required=False, widget=ImagePreviewWidget
    )
    private = forms.BooleanField(
        label=_("Private"),
        required=False,
        help_text=_("Only members of this organization will be able to view it"),
    )

    class Meta:
        model = Organization
        fields = ["avatar", "private"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset("Avatar", Field("avatar"), css_class="_cls-compactField"),
            Fieldset("Private", Field("private"), css_class="_cls-compactField"),
        )
        self.helper.form_tag = False


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    email = forms.EmailField()
