# Django
from django import forms
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field as CrispyField, Fieldset, Layout

# Squarelet
from squarelet.core.fields import EmailsListField
from squarelet.core.forms import AvatarWidget
from squarelet.organizations.models import OrganizationEmailDomain

# Local
from .choices import InvitationRole
from .models import Organization, ProfileChangeRequest


class CreateForm(forms.ModelForm):
    """Form for creating a new organization"""

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

    class Meta:
        model = Organization
        fields = ["name", "about", "avatar"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.template_pack = "forms"
        self.helper.layout = Layout(
            CrispyField("name"),
            CrispyField("avatar"),
            CrispyField("about"),
        )
        self.helper.form_tag = False


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

    emails = EmailsListField(required=False)
    user_ids = forms.CharField(required=False)
    role = forms.ChoiceField(
        label=_("Role"),
        choices=InvitationRole.choices,
        initial=InvitationRole.member,
        required=False,
        widget=forms.RadioSelect,
        help_text=_(
            "Members can view organization content. "
            "Admins can also manage members and settings."
        ),
    )

    def clean_user_ids(self):
        raw = self.cleaned_data.get("user_ids", "")
        if not raw.strip():
            return []
        return [int(uid) for uid in raw.split(",") if uid.strip().isdigit()]

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("emails") and not cleaned_data.get("user_ids"):
            raise forms.ValidationError(
                _("Select at least one user or enter an email address.")
            )
        return cleaned_data


class InvitationAcceptForm(forms.Form):
    """
    Validates that a user can accept an invitation.
    Admin-role invitations require the user to have a verified email address.
    Exposes a class method to bind the class to an Invitation object.
    """

    template_name = "organizations/invitation_accept_form.html"

    def __init__(self, *args, invitation, user, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invitation = invitation
        self.user = user
        self.request = request

    @property
    def requires_email_verification(self):
        return (
            self.invitation.role == InvitationRole.admin
            and not self.user.emailaddress_set.filter(verified=True).exists()
        )

    def clean(self):
        cleaned_data = super().clean()
        if self.requires_email_verification:
            raise forms.ValidationError(
                _(
                    "You must verify your email address before accepting "
                    "an admin invitation."
                )
            )
        return cleaned_data

    def get_context(self):
        context = super().get_context()
        context["invitation"] = self.invitation
        context["user"] = self.user
        context["requires_email_verification"] = self.requires_email_verification
        if self.request:
            context["csrf_token"] = get_token(self.request)
        return context

    @classmethod
    def attach_to_invitations(cls, invitations, user, request=None):
        """Attach an accept_form to each invitation in the list."""
        for invitation in invitations:
            invitation.accept_form = cls(
                invitation=invitation, user=user, request=request
            )
        return invitations


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
        user = getattr(self.request, "user", None)

        super().__init__(*args, **kwargs)

        # Set help text
        self.fields["url"].help_text = _(
            "Add a URL to associate with this organization."
        )
        self.fields["explanation"].help_text = _(
            "Explain why you are requesting these changes "
            "(required for staff review)."
        )
        self.fields["explanation"].required = not getattr(user, "is_staff", False)

        for field in ProfileChangeRequest.FIELDS:
            current = getattr(self.instance.organization, field, None)
            if current:
                self.fields[field].widget.attrs["placeholder"] = current

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

        # Only keep fields that have changed from their initial values
        fields_to_check = ["name", "slug", "url", "city", "state", "country"]
        changed_fields = []

        for field in fields_to_check:
            initial_value = getattr(self.instance.organization, field, None)
            new_value = cleaned_data.get(field)

            # If the value hasn't changed, clear it
            if new_value == initial_value:
                cleaned_data[field] = ""
            elif new_value:
                changed_fields.append(field)

        # Check if URL already exists for this organization
        if cleaned_data.get("url") and self.instance and self.instance.organization:
            if self.instance.organization.urls.filter(url=cleaned_data["url"]).exists():
                raise forms.ValidationError(
                    {"url": _("This URL is already associated with the organization.")}
                )

        # At least one field must have changed
        if not changed_fields:
            raise forms.ValidationError(_("You must change at least one field."))

        # Explanation is required for non-staff users when requesting changes
        if self.request and not self.request.user.is_staff:
            if not cleaned_data.get("explanation"):
                raise forms.ValidationError(
                    _("Please provide an explanation for your requested changes.")
                )

        return cleaned_data


class DomainActionForm(forms.Form):
    """Form for adding or removing an organization email domain."""

    ACTION_ADD = "adddomain"
    ACTION_REMOVE = "removedomain"
    ACTION_CHOICES = [
        (ACTION_ADD, _("Add domain")),
        (ACTION_REMOVE, _("Remove domain")),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    domain = forms.CharField(max_length=255)

    def __init__(self, *args, available_domains=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.available_domains = available_domains or []
        self.organization = organization

    def clean_domain(self):
        return self.cleaned_data["domain"].strip().lower()

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        domain = cleaned_data.get("domain")

        # If either required field is missing, we can bail early.
        # The form is already invalid and field-level validators
        # will raise form errors for missing required fields.
        if not action or not domain:
            return cleaned_data

        if action == self.ACTION_ADD:
            if domain not in self.available_domains:
                raise forms.ValidationError(
                    _(
                        "Invalid domain. Please select a domain from "
                        "your verified emails."
                    )
                )
        elif action == self.ACTION_REMOVE:
            try:
                cleaned_data["domain_entry"] = OrganizationEmailDomain.objects.get(
                    organization=self.organization, domain=domain
                )
            except OrganizationEmailDomain.DoesNotExist:
                raise forms.ValidationError(
                    _(
                        f"The domain {domain} was not found or "
                        "has already been removed."
                    )
                )

        return cleaned_data
