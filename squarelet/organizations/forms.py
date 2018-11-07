# Django
from django import forms
from django.core.validators import validate_email
from django.utils.translation import ugettext_lazy as _

# Local
from .choices import Plan
from .constants import MIN_USERS


class StripeForm(forms.Form):
    """Base class for forms which include stripe fields"""

    stripe_token = forms.CharField(widget=forms.HiddenInput())
    use_card_on_file = forms.TypedChoiceField(
        label=_("Use Credit Card on File"),
        coerce=lambda x: x == "True",
        initial=True,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance")
        super().__init__(*args, **kwargs)
        self._set_card_options()

    def _set_card_options(self):
        card = self.organization.card
        if card:
            self.fields["use_card_on_file"].choices = (
                (True, f"{card.brand}: {card.last4}"),
                (False, "New Card"),
            )
            self.fields["stripe_token"].required = False
        else:
            del self.fields["use_card_on_file"]


class UpdateForm(StripeForm):
    """Update an organization"""

    plan = forms.TypedChoiceField(label=_("Type"), coerce=int)
    max_users = forms.IntegerField(
        label=_("Number of Users"), min_value=MIN_USERS[Plan.basic]
    )
    private = forms.BooleanField(label=_("Private"), required=False)
    receipt_emails = forms.CharField(
        label=_("Receipt Emails"),
        widget=forms.Textarea(),
        required=False,
        help_text=_("One email address per line"),
    )

    field_order = [
        "stripe_token",
        "plan",
        "max_users",
        "private",
        "receipt_emails",
        "use_card_on_file",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_group_options()

    def _set_group_options(self):
        if self.organization.individual:
            self.fields["plan"].choices = Plan.individual_choices()
            del self.fields["max_users"]
            del self.fields["private"]
        else:
            self.fields["plan"].choices = Plan.group_choices()
            limit_value = max(MIN_USERS[Plan.basic], self.organization.user_count())
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


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    email = forms.EmailField()


class BuyRequestsForm(StripeForm):
    """A form to buy ala carte requests"""

    number_requests = forms.IntegerField(
        label=_("Number of requests to buy"), min_value=1
    )
    save_card = forms.BooleanField(
        label=_("Save credit card information"), required=False
    )

    field_order = ["stripe_token", "number_requests", "use_card_on_file", "save_card"]

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("save_card") and not cleaned_data.get("stripe_token"):
            self.add_error(
                "save_card",
                _("You must enter credit card information in order to save it"),
            )
        if cleaned_data.get("save_card") and cleaned_data.get("use_card_on_file"):
            self.add_error(
                "save_card",
                _(
                    "You cannot save your card information if you are using your "
                    "card on file."
                ),
            )
        if cleaned_data.get("use_card_on_file") and cleaned_data.get("stripe_token"):
            self.add_error(
                "use_card_on_file",
                _("You cannot use your card on file and enter a credit card number."),
            )
        return cleaned_data


class ManageMembersForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance")
        super().__init__(*args, **kwargs)
        memberships = self.organization.memberships.select_related("user")
        for membership in memberships:
            self.fields[f"remove-{membership.user.pk}"] = forms.BooleanField(
                required=False
            )
            self.fields[f"admin-{membership.user.pk}"] = forms.BooleanField(
                required=False, initial=membership.admin
            )


class ManageInvitationsForm(forms.Form):
    """Manage pending and requested invitations for an organization"""

    action = forms.ChoiceField(
        widget=forms.HiddenInput(), choices=(("accept", "Accept"), ("revoke", "Revoke"))
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("instance")
        super().__init__(*args, **kwargs)

        pending_invitations = self.organization.invitations.get_pending()
        for invitation in pending_invitations:
            self.fields[f"remove-{invitation.pk}"] = forms.BooleanField(required=False)

        requested_invitations = self.organization.invitations.get_requested()
        for invitation in requested_invitations:
            self.fields[f"accept-{invitation.pk}"] = forms.BooleanField(required=False)

    def clean(self):
        """Ensure we don't go over our max users"""
        cleaned_data = super().clean()
        if cleaned_data["action"] == "accept":
            new_user_count = len(
                [k for k, v in cleaned_data.items() if k.startswith("accept") and v]
            )
            if (
                self.organization.user_count() + new_user_count
                > self.organization.max_users
            ):
                raise forms.ValidationError(
                    _("You must add more max users before accepting those invitations")
                )
