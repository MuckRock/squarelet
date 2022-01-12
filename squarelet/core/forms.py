# Django
from django import forms
from django.conf import settings
from django.forms.widgets import ClearableFileInput
from django.utils.translation import gettext_lazy as _

# Squarelet
from squarelet.organizations.choices import StripeAccounts


class StripeForm(forms.Form):
    """Base class for forms which include stripe fields"""

    # this form always uses MuckRock's stripe account
    stripe_pk = forms.CharField(
        widget=forms.HiddenInput(),
        initial=settings.STRIPE_PUB_KEYS[StripeAccounts.muckrock],
    )
    stripe_token = forms.CharField(widget=forms.HiddenInput(), required=False)
    use_card_on_file = forms.TypedChoiceField(
        label=_("Use Credit Card on File"),
        coerce=lambda x: x == "True",
        initial=True,
        widget=forms.RadioSelect,
    )
    remove_card_on_file = forms.BooleanField(initial=False, required=False)

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        self._set_card_options()

    def _set_card_options(self):
        card = None
        if self.organization:
            customer = self.organization.customer(StripeAccounts.muckrock)
            card = customer.card
        if card:
            self.fields["use_card_on_file"].choices = (
                (True, customer.card_display),
                (False, _("New Card")),
            )
            self.fields["remove_card_on_file"].label = customer.card_display
        else:
            del self.fields["use_card_on_file"]
            del self.fields["remove_card_on_file"]
            self.fields["stripe_token"].required = True

    def clean(self):
        data = super().clean()
        if data.get("use_card_on_file") and data.get("stripe_token"):
            self.add_error(
                "use_card_on_file",
                _("You cannot use your card on file and enter a credit card number."),
            )
        return data


class ImagePreviewWidget(ClearableFileInput):
    template_name = "widgets/image_field.html"
