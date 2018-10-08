
# Django
from django import forms
from django.utils.translation import ugettext_lazy as _

# Local
from .choices import OrgType


class UpdateForm(forms.Form):
    """Update an organization"""

    stripe_token = forms.CharField(widget=forms.HiddenInput())
    org_type = forms.TypedChoiceField(label=_("Type"), coerce=int)
    max_users = forms.IntegerField(label=_("Number of Users"), min_value=5)
    private = forms.BooleanField(label=_("Private"), required=False)
    use_card_on_file = forms.TypedChoiceField(
        label=_("Use Credit Card on File"),
        coerce=lambda x: x == "True",
        initial=True,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance")
        kwargs["initial"] = {
            "org_type": self.organization.org_type,
            "max_users": self.organization.max_users,
            "private": self.organization.private,
        }
        super().__init__(*args, **kwargs)
        self._set_group_options()
        self._set_card_options()

    def _set_group_options(self):
        if self.organization.individual:
            self.fields["org_type"].choices = OrgType.individual_choices()
            del self.fields["max_users"]
        else:
            self.fields["org_type"].choices = OrgType.group_choices()
            # XXX 5 should be a constant
            self.fields["max_users"].min_value = max(5, self.organization.users.count())

    def _set_card_options(self):
        card = self.organization.card()
        if card:
            self.fields["use_card_on_file"].choices = (
                (True, f"{card.brand}: {card.last4}"),
                (False, "New Card"),
            )
            self.fields["stripe_token"].required = False
        else:
            del self.fields["use_card_on_file"]


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    email = forms.EmailField()
