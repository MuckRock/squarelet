# Django
from django import forms
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

# Standard Library
import re

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field as CrispyField, Layout

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.core.layout import Field  # Used by PaymentForm
from squarelet.organizations.models import Organization, Plan


class CardForm(StripeForm):
    """Update the credit card on file for an organization."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This form is only for replacing the current card, so these fields aren't used
        self.fields.pop("use_card_on_file", None)
        self.fields.pop("remove_card_on_file", None)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("stripe_pk"),
            Field("stripe_token"),
        )
        self.helper.form_tag = False


class UpdateSubscriptionFrequencyForm(forms.ModelForm):
    """Update the frequency of a subscription."""

    class Meta:
        model = Plan
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False


class UpdateReceiptEmailForm(forms.ModelForm):
    """Update the receipt email for an organization."""

    receipt_emails = forms.CharField(
        label=_("Receipt emails"),
        widget=forms.TextInput(),
        required=True,
        help_text=_("Enter one or more email addresses, separated by commas"),
    )

    class Meta:
        model = Organization
        fields = ["receipt_emails"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.template_pack = "forms"
        self.helper.layout = Layout(
            CrispyField("receipt_emails"),
        )
        self.helper.form_tag = False

    def clean_receipt_emails(self):
        """Make sure each entry is a valid email"""
        emails = re.split(r",\s*", self.cleaned_data["receipt_emails"])
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


class CancelSubscriptionForm(forms.ModelForm):
    """Cancel a subscription."""

    class Meta:
        model = Organization
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
