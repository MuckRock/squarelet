# Django
from django import forms
from django.core.validators import validate_email
from django.utils.translation import ugettext_lazy as _

# Squarelet
from squarelet.core.forms import StripeForm

# Local
from .models import Plan


class UpdateForm(StripeForm):
    """Update an organization"""

    plan = forms.ModelChoiceField(label=_("Plan"), queryset=Plan.objects.none())
    max_users = forms.IntegerField(label=_("Number of Users"), min_value=5)
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
        self.fields["stripe_token"].required = False
        self._set_group_options()

    def _set_group_options(self):
        if self.organization.individual:
            self.fields["plan"].queryset = Plan.objects.individual_choices()
            del self.fields["max_users"]
            del self.fields["private"]
        else:
            self.fields["plan"].queryset = Plan.objects.group_choices()
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
        data = super().clean()
        if data.get("save_card") and not data.get("stripe_token"):
            self.add_error(
                "save_card",
                _("You must enter credit card information in order to save it"),
            )
        if data.get("save_card") and data.get("use_card_on_file"):
            self.add_error(
                "save_card",
                _(
                    "You cannot save your card information if you are using your "
                    "card on file."
                ),
            )

        if (
            "use_card_on_file" in self.fields
            and not data.get("use_card_on_file")
            and not data.get("stripe_token")
        ):
            self.add_error(
                "use_card_on_file",
                _("You must use your card on file or enter a credit card number."),
            )
        return data


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    email = forms.EmailField()


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
