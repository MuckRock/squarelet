# Django
from django import forms
from django.core.validators import validate_email
from django.db.models.aggregates import Min
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout, Field as CrispyField

# Squarelet
from squarelet.core.fields import EmailsListField
from squarelet.core.forms import AvatarWidget, StripeForm
from squarelet.core.layout import Field  # Used by PaymentForm

# Local
from .models import Organization, Plan, ProfileChangeRequest


class PaymentForm(StripeForm):
    """Update subscription information for an organization"""

    plan = forms.ModelChoiceField(
        label=_("Plan"),
        queryset=Plan.objects.none(),
        empty_label="Free",
        required=False,
    )
    max_users = forms.IntegerField(
        label=_("Number of Resource Blocks"),
        min_value=1,
        help_text=_(" "),
    )
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
                Fieldset(
                    "Resource Blocks", Field("max_users"), css_class="_cls-compactField"
                )
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
            plan_minimum = plans.aggregate(minimum=Min("minimum_users"))["minimum"]
            if plan_minimum is None:
                plan_minimum = 1
            self.fields["max_users"].validators[0].limit_value = plan_minimum
            self.fields["max_users"].widget.attrs["min"] = plan_minimum
            self.fields["max_users"].initial = plan_minimum

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
        label=_("Avatar"),
        required=False,
        widget=AvatarWidget,
        help_text=(
            "This will represent the organization on its profile, "
            "on public pages, and in lists."
        ),
    )
    about = forms.CharField(
        label=_("About"),
        widget=forms.Textarea,
        required=False,
        help_text=_("Markdown formatting supported. Maximum 250 characters."),
    )
    private = forms.BooleanField(
        label=_("Private"),
        required=False,
        help_text=_("Only members of this organization will be able to view it"),
    )
    allow_auto_join = forms.BooleanField(
        label=_("Allow Auto Join"),
        required=False,
        help_text=_(
            "Allow users to join this organization without an invite"
            "if one of their verified emails matches "
            "one of the organization's email domains."
        ),
    )

    class Meta:
        model = Organization
        fields = ["avatar", "about", "private", "allow_auto_join"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.verified_journalist:
            domains = self.instance.domains.values_list("domain", flat=True)
            domain_list = ", ".join(f"<b> {d}</b>" for d in domains)
            manage_domains_url = reverse(
                "organizations:manage-domains", kwargs={"slug": self.instance.slug}
            )
            if domain_list:
                self.fields["allow_auto_join"].help_text = _(
                    "Allow users to join without an invite "
                    "if one of their verified emails matches one of "
                    "the organization's email domains. "
                    "This organization has the following email domains set:"
                    f"{domain_list}. "
                    f"<a href='{manage_domains_url}'>"
                    " Edit this list of email domains</a>."
                )
            else:
                self.fields["allow_auto_join"].help_text = _(
                    "Allow users to join without requesting "
                    "an invite if one of their verified emails matches one of the "
                    "organization's email domains. No email domains currently set. "
                    f"<a href='{manage_domains_url}'>Add one now</a>."
                )
        else:
            self.fields.pop("allow_auto_join", None)

        self.helper = FormHelper()
        self.helper.template_pack = "forms"
        self.helper.layout = Layout(
            CrispyField("avatar"),
            CrispyField("about"),
            CrispyField("private"),
        )

        if "allow_auto_join" in self.fields:
            self.helper.layout.fields.append(CrispyField("allow_auto_join"))
        self.helper.form_tag = False


class AddMemberForm(forms.Form):
    """Add a member to the organization"""

    emails = EmailsListField()


class MergeForm(forms.Form):
    """A form to merge two organizations"""

    good_organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(individual=False, merged=None),
        label=_('"Good" organization to keep'),
    )
    bad_organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(
            subscriptions__isnull=True,
            individual=False,
            merged=None,
        ),
        label=_('"Bad" organization to reject'),
    )
    confirmed = forms.BooleanField(
        initial=False, widget=forms.HiddenInput(), required=False
    )

    def __init__(self, *args, **kwargs):
        confirmed = kwargs.pop("confirmed", False)
        super().__init__(*args, **kwargs)
        if confirmed:
            self.fields["confirmed"].initial = True
            self.fields["good_organization"].widget = forms.HiddenInput()
            self.fields["bad_organization"].widget = forms.HiddenInput()

        self.helper = FormHelper()
        self.helper.form_tag = False

    def clean(self):
        cleaned_data = super().clean()
        good_organization = cleaned_data.get("good_organization")
        bad_organization = cleaned_data.get("bad_organization")
        if good_organization and good_organization == bad_organization:
            raise forms.ValidationError("Cannot merge an organization into itself")
        return cleaned_data


class ProfileChangeRequestForm(forms.ModelForm):
    """Request changes to core organization profile data"""

    url = forms.URLField(label=_("URL"), required=False)

    class Meta:
        model = ProfileChangeRequest
        fields = ["name", "slug", "url", "city", "state", "country", "explanation"]

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # Populate placeholders with current organization values
        if self.instance and self.instance.organization:
            org = self.instance.organization
            self.fields["name"].widget.attrs["placeholder"] = org.name
            self.fields["slug"].widget.attrs["placeholder"] = org.slug
            self.fields["city"].widget.attrs["placeholder"] = org.city or _("City")
            self.fields["state"].widget.attrs[
                "placeholder"
            ] = org.get_state_display() or _("State")
            self.fields["country"].widget.attrs[
                "placeholder"
            ] = org.get_country_display() or _("Country")

            # Update help text to show current values
            self.fields["name"].help_text = _(
                f"Current: {org.name}. Leave blank to keep unchanged."
            )
            self.fields["slug"].help_text = _(
                f"Current: {org.slug}. Leave blank to keep unchanged."
            )
            self.fields["city"].help_text = _(
                f"Current: {org.city or 'Not set'}. Leave blank to keep unchanged."
            )
            self.fields["state"].help_text = _(
                f"Current: {org.get_state_display() or 'Not set'}. "
                "Leave blank to keep unchanged."
            )
            self.fields["country"].help_text = _(
                f"Current: {org.get_country_display() or 'Not set'}. "
                "Leave blank to keep unchanged."
            )
            self.fields["url"].help_text = _(
                "Add a URL to associate with this organization."
            )
            self.fields["explanation"].help_text = _(
                "Explain why you are requesting these changes "
                "(required for staff review)."
            )

        self.helper = FormHelper()
        self.helper.template_pack = "forms"
        self.helper.layout = Layout(
            CrispyField("name"),
            CrispyField("slug"),
            CrispyField("url"),
            Fieldset(
                "Location",
                CrispyField("city"),
                CrispyField("state"),
                CrispyField("country"),
            ),
            CrispyField("explanation"),
        )
        self.helper.form_tag = False

    def clean(self):
        cleaned_data = super().clean()

        # At least one field must be filled
        fields_to_check = ["name", "slug", "url", "city", "state", "country"]
        if not any(cleaned_data.get(field) for field in fields_to_check):
            raise forms.ValidationError(
                _("You must provide at least one field to change.")
            )

        # Explanation is required for non-staff users when requesting changes
        if self.request and not self.request.user.is_staff:
            if not cleaned_data.get("explanation"):
                raise forms.ValidationError(
                    _("Please provide an explanation for your requested changes.")
                )

        return cleaned_data
