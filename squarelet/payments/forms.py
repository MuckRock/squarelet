"""Forms for managing cards, receipt emails and subscriptions"""

# Django
from django import forms
from django.utils.translation import gettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field as CrispyField, Layout

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.core.layout import Field
from squarelet.organizations.models import Organization


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


class UpdateReceiptEmailForm(forms.ModelForm):
    """Update the receipt email for an organization."""

    receipt_email = forms.CharField(
        label=_("Receipt email"),
        widget=forms.TextInput(),
        required=True,
        help_text=_("Email address for billing communications"),
    )

    class Meta:
        model = Organization
        fields = ["receipt_email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.template_pack = "forms"
        self.helper.layout = Layout(
            CrispyField("receipt_email"),
        )
        self.helper.form_tag = False


class CancelSubscriptionForm(forms.ModelForm):
    """Cancel a subscription."""

    class Meta:
        model = Organization
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
