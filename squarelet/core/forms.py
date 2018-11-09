# Django
from django import forms
from django.utils.translation import ugettext_lazy as _

# XXX refactor for which of use_card_on_file / save_card you need


class StripeForm(forms.Form):
    """Base class for forms which include stripe fields"""

    stripe_token = forms.CharField(widget=forms.HiddenInput(), required=False)
    use_card_on_file = forms.TypedChoiceField(
        label=_("Use Credit Card on File"),
        coerce=lambda x: x == "True",
        initial=True,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        self._set_card_options()

    def _set_card_options(self):
        card = self.organization and self.organization.card
        if card:
            self.fields["use_card_on_file"].choices = (
                (True, f"{card.brand}: {card.last4}"),
                (False, "New Card"),
            )
        else:
            del self.fields["use_card_on_file"]
            self.fields["stripe_token"].required = True

    def clean(self):
        data = super().clean()
        if data.get("use_card_on_file") and data.get("stripe_token"):
            self.add_error(
                "use_card_on_file",
                _("You cannot use your card on file and enter a credit card number."),
            )
        return data
