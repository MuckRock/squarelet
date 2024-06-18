# Django
from django import forms
from django.core.validators import validate_email
from django.db.models.aggregates import Min
from django.utils.translation import gettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout

# Squarelet
from squarelet.core.fields import EmailsListField
from squarelet.core.forms import ImagePreviewWidget, StripeForm
from squarelet.core.layout import Field

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
    max_users = forms.IntegerField(label=_("Number of Users"), min_value=1)
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
            (
                Fieldset("Max Users", Field("max_users"), css_class="_cls-compactField")
                if "max_users" in self.fields
                else None
            ),
            Fieldset(
                "Receipt emails",
                Field("receipt_emails", id="_id-receiptEmails"),
                css_class="_cls-resizeField",
            ),
            (
                Fieldset(
                    "Credit card",
                    Field("use_card_on_file"),
                    css_class="_cls-compactField",
                    id="_id-cardFieldset",
                )
                if "use_card_on_file" in self.fields
                else None
            ),
            (
                Fieldset(
                    "Remove credit card on file",
                    Field("remove_card_on_file"),
                    css_class="_cls-compactField",
                    id="_id-removeCardFieldset",
                )
                if "remove_card_on_file" in self.fields
                else None
            ),
        )
        self.helper.form_tag = False

    def _set_group_options(self):
        # only show public options, plus the current plan, in case they are currently
        # on a private plan, plus private plans they have been given access to
        plans = Plan.objects.choices(self.organization)
        self.fields["plan"].queryset = plans
        self.fields["plan"].default = self.organization.plan
        if self.organization.individual:
            del self.fields["max_users"]
        else:
            seat_count = self.organization.user_count()
            plan_minimum = plans.aggregate(minimum=Min("minimum_users"))["minimum"]
            limit_value = max(plan_minimum, seat_count)
            self.fields["max_users"].validators[0].limit_value = limit_value
            self.fields["max_users"].widget.attrs["min"] = limit_value
            self.fields["max_users"].initial = limit_value
            if limit_value > plan_minimum:
                self.fields["max_users"].help_text = (
                    "You currently have "
                    f"{self.organization.users.count()} users and "
                    f"{self.organization.invitations.get_pending().count()} pending "
                    f"invitations for this organization, for a total of "
                    f"{seat_count}.  You may not set this value lower than that."
                )

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
            bad_emails_str = ", ".join(bad_emails)
            raise forms.ValidationError(f"Invalid email: {bad_emails_str}")
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

        if payment_required and data.get("remove_card_on_file"):
            self.add_error(
                None, _("You cannot remove your card on file if you have a paid plan")
            )

        if data.get("remove_card_on_file") and not self.organization.customer().card:
            self.add_error(None, _("You do not have a card on file to remove"))

        if plan and "max_users" in data and data["max_users"] < plan.minimum_users:
            self.add_error(
                "max_users",
                _(f"The minimum users for the {plan} plan is {plan.minimum_users}"),
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

    emails = EmailsListField()
