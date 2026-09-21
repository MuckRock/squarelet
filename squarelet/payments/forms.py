"""Forms for plan purchase functionality"""

# Django
from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys

# Third Party
import stripe
from allauth.account.adapter import get_adapter
from allauth.account.utils import has_verified_email
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field as CrispyField, Layout

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.core.layout import Field
from squarelet.organizations.models import Organization, PlanPrice, SubscriptionItem
from squarelet.organizations.models.payment import get_payment_brand
from squarelet.users.forms import NewOrganizationModelChoiceField

logger = logging.getLogger(__name__)


class PlanPurchaseForm(StripeForm):
    """
    Form for purchasing a plan subscription.

    Handles:
    - Organization selection (individual, admin orgs, or new)
    - Payment method selection (existing-card, new-card, invoice)
    - Nonprofit discount for Sunlight plans
    - Stripe token handling

    Usage:
        form = PlanPurchaseForm(plan=plan, user=request.user)

    In templates, renders with {{ form }} using the custom template_name.
    """

    template_name = "payments/forms/plan_purchase.html"

    # Payment method choices
    PAYMENT_METHOD_CHOICES = [
        ("existing-card", _("Use existing card")),
        ("new-card", _("Use new card")),
        ("invoice", _("Pay by invoice")),
    ]

    organization = NewOrganizationModelChoiceField(
        label=_("Organization"),
        queryset=None,  # Set dynamically in __init__
        required=True,
        empty_label=_("Choose an organization"),
    )

    new_organization_name = forms.CharField(
        label=_("Organization name"),
        required=False,
        max_length=255,
        widget=forms.TextInput(),
    )

    payment_method = forms.ChoiceField(
        label=_("Payment method"),
        choices=PAYMENT_METHOD_CHOICES,
        required=False,
        widget=forms.RadioSelect(),
    )

    is_nonprofit = forms.BooleanField(
        label=_("My organization is non-profit"),
        required=False,
        help_text=_(
            "Non-profit organizations receive a discount on "
            "Sunlight Research Desk plans."
        ),
    )

    save_card = forms.BooleanField(
        label=_("Save as default card"),
        required=False,
        initial=True,
    )

    purchase_redirect = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    # Which of the plan's prices this purchase is for.  A canonical tier is
    # one row with a monthly and an annual price; the page chose one and
    # the form carries the choice back so the purchase resolves the same
    # price the page showed.
    price_interval = forms.ChoiceField(
        choices=PlanPrice.INTERVAL_CHOICES,
        required=False,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, plan=None, user=None, interval=None, **kwargs):
        """
        Initialize the form with plan and user context.

        Args:
            plan: The Plan instance being purchased
            user: The authenticated User instance
            interval: which of the plan's prices, when it has more than one
        """
        # Don't pass instance to parent - we handle organization differently
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)

        self.plan = plan
        self.user = user
        self.fields["stripe_token"].required = False

        # The price this form sells, read the way the purchase will read
        # it.  None means the plan is not for sale at that interval; the
        # template says so instead of rendering a form.
        self.intervals = (
            SubscriptionItem.objects.intervals_for_sale(plan) if plan else []
        )
        if interval is None and self.is_bound:
            interval = self.data.get("price_interval") or None
        if interval not in self.intervals:
            interval = self.intervals[0] if self.intervals else None
        self.interval = interval
        self.fields["price_interval"].initial = interval
        self.price = plan.price_for(interval) if plan and interval else None
        self.nonprofit_price = None
        if self.price is not None:
            candidate = plan.price_for(interval, nonprofit=True)
            if candidate.label == "nonprofit":
                self.nonprofit_price = candidate

        # Remove inherited fields we don't use from StripeForm
        if "use_card_on_file" in self.fields:
            del self.fields["use_card_on_file"]
        if "remove_card_on_file" in self.fields:
            del self.fields["remove_card_on_file"]

        self._configure_organization_field()
        self._configure_payment_method_field()
        self._configure_nonprofit_field()

    def _configure_organization_field(self):
        """Configure organization queryset based on user and plan"""
        if self.user and self.user.is_authenticated:
            individual_org = self.user.individual_organization

            # Start with organizations where user is admin
            admin_orgs = Organization.objects.filter(
                memberships__user=self.user,
                memberships__admin=True,
                individual=False,
            ).distinct()

            # Filter by plan's private organizations if applicable
            if (
                self.plan
                and not self.plan.public
                and self.plan.private_organizations.exists()
            ):
                admin_orgs = admin_orgs.filter(
                    pk__in=self.plan.private_organizations.all()
                )

            # Build queryset based on plan type
            if self.plan:
                if self.plan.for_individuals and self.plan.for_groups:
                    # Both individuals and groups allowed
                    base_queryset = Organization.objects.filter(
                        Q(pk=individual_org.pk) | Q(pk__in=admin_orgs)
                    ).distinct()
                elif self.plan.for_individuals and not self.plan.for_groups:
                    # Individual only
                    base_queryset = Organization.objects.filter(pk=individual_org.pk)
                elif self.plan.for_groups and not self.plan.for_individuals:
                    # Groups only
                    base_queryset = admin_orgs
                else:
                    # Neither - shouldn't happen but handle gracefully
                    base_queryset = Organization.objects.none()
            else:
                # No plan specified - show all
                base_queryset = Organization.objects.filter(
                    Q(pk=individual_org.pk) | Q(pk__in=admin_orgs)
                ).distinct()

            # A cancelled line still occupies the plan - `unique_together`
            # is (subscription, plan) - and `add_subscription` refuses a
            # duplicate.  Reviving one is what Resubscribe is for.
            if self.plan:
                subscribed_orgs = Organization.objects.filter(
                    subscriptions__items__plan=self.plan,
                )
                base_queryset = base_queryset.exclude(pk__in=subscribed_orgs)

            self.fields["organization"].queryset = base_queryset
        else:
            self.fields["organization"].queryset = Organization.objects.none()

    def _configure_payment_method_field(self):
        """Configure payment method choices based on plan"""
        choices = [
            ("existing-card", _("Use card on file")),
            ("new-card", _("Use new card")),
        ]

        # Invoice option only for annual prices
        if self.interval == "annual":
            choices.append(("invoice", _("Pay by invoice")))

        self.fields["payment_method"].choices = choices

    def _configure_nonprofit_field(self):
        """Offer the nonprofit box only where there is a nonprofit rate.

        Whether a plan has one is a fact about its prices, not about which
        product it is marketed under - Sunlight is the only product with
        one today, and this stays right if that changes.
        """
        if self.nonprofit_price is None:
            del self.fields["is_nonprofit"]

    def user_has_verified_email(self):
        """
        Whether the form's user has a verified email address.

        Used by the template to decide whether to offer the
        "Create a new organization" option, mirroring the server-side
        constraint enforced in clean().
        """
        return has_verified_email(self.user)

    def get_org_cards_data(self):
        """
        Build a mapping of organization IDs to their saved card info.
        Used by the frontend to dynamically update payment options.

        Returns:
            dict: Mapping of org_id (str) to card info dict with 'last4' and 'brand'
        """
        org_cards = {}
        if not self.user or not self.user.is_authenticated:
            return org_cards

        for org in self.fields["organization"].queryset:
            try:
                card = org.customer().payment_details
                if card:
                    org_cards[str(org.pk)] = {
                        "last4": card.last4,
                        "brand": get_payment_brand(card),
                    }
            except stripe.error.StripeError as exc:
                logger.error(
                    "Error fetching card for org %s: %s",
                    org.pk,
                    exc,
                    exc_info=sys.exc_info(),
                )

        return org_cards

    def get_plan_data(self):
        """
        Build plan data for frontend JavaScript.

        Returns:
            dict: Plan information for JS
        """
        if self.price is None:
            return {}

        data = {
            "interval": self.price.interval,
            "amount": self.price.amount_dollars,
            "has_nonprofit_variant": self.nonprofit_price is not None,
        }
        if self.nonprofit_price is not None:
            data["nonprofit_amount"] = self.nonprofit_price.amount_dollars
        return data

    def clean_new_organization_name(self):
        """Validate new organization name is provided when creating new org"""
        name = self.cleaned_data.get("new_organization_name", "").strip()
        organization = self.data.get("organization")

        if organization == "new" and not name:
            raise forms.ValidationError(
                _("Please provide a name for the new organization")
            )

        return name

    def clean_purchase_redirect(self):
        """Validate that purchase_redirect is a safe absolute URL if provided"""
        url = self.cleaned_data.get("purchase_redirect", "").strip()
        adapter = get_adapter()
        if url and adapter.is_safe_url(url):
            return url
        return ""

    def clean_is_nonprofit(self):
        """The box is only offered where there is a rate; refuse it elsewhere"""
        is_nonprofit = self.cleaned_data.get("is_nonprofit", False)

        if is_nonprofit and self.nonprofit_price is None:
            raise forms.ValidationError(_("There is no non-profit rate for this plan"))

        return is_nonprofit

    def clean_price_interval(self):
        """The interval the page showed, or the plan's first one."""
        return self.interval

    def clean(self):
        """
        Cross-field validation for payment method and organization.
        """
        data = super().clean()

        organization = data.get("organization")
        payment_method = data.get("payment_method")
        stripe_token = data.get("stripe_token")

        # Users must verify an email address before creating a new organization
        if organization == "new" and not has_verified_email(self.user):
            self.add_error(
                "organization",
                _(
                    "You must verify your email address before "
                    "creating an organization."
                ),
            )

        # Validate payment method matches available options
        if payment_method == "existing-card":
            if organization and organization != "new":
                if not organization.customer().payment_details:
                    self.add_error(
                        "payment_method",
                        _("No payment method on file. Please add a card."),
                    )
        elif payment_method == "new-card":
            if not stripe_token:
                self.add_error(
                    "stripe_token",
                    _("Please provide card information."),
                )
        elif payment_method == "invoice":
            if self.interval != "annual":
                self.add_error(
                    "payment_method",
                    _("Invoice payment is only available for annual plans."),
                )

        return data

    def get_or_create_organization(self, user):
        """
        Get or create the organization for the subscription.

        Args:
            user: The user creating the subscription

        Returns:
            Organization instance
        """
        organization = self.cleaned_data.get("organization")

        if organization == "new":
            # Defense in depth: clean() rejects new-org creation for users
            # without a verified email, but guard here as well since this is
            # the actual creation point.
            if not has_verified_email(user):
                raise forms.ValidationError(
                    _(
                        "You must verify your email address before "
                        "creating an organization."
                    )
                )
            new_org = Organization.objects.create(
                name=self.cleaned_data["new_organization_name"],
                private=False,
            )
            new_org.add_creator(user)
            return new_org
        elif organization:
            return organization
        else:
            return user.individual_organization

    def save(self, user):
        """
        Process the subscription.

        Note: This does NOT create the subscription directly.
        It returns the data needed for the view to create the subscription
        with appropriate transaction handling.

        Args:
            user: The authenticated user

        Returns:
            dict with organization, plan, interval, payment_method,
            stripe_token and nonprofit
        """
        organization = self.get_or_create_organization(user)

        return {
            "organization": organization,
            # The row the customer picked.  Nonprofit used to substitute a
            # `sunlight-nonprofit-*` row in here; it is a label on the
            # price now, and `nonprofit` below chooses it.
            "plan": self.plan,
            "interval": self.interval,
            "payment_method": self.cleaned_data.get("payment_method"),
            "stripe_token": self.cleaned_data.get("stripe_token"),
            # Self-reported, on the honour system, and only offered where
            # the plan has a nonprofit price.  It chooses which PlanPrice
            # the subscription is sold at.
            "nonprofit": self.cleaned_data.get("is_nonprofit", False),
        }


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
