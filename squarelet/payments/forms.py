"""Forms for plan purchase functionality"""

# Django
from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

# Standard Library
import json

# Squarelet
from squarelet.core.forms import StripeForm
from squarelet.organizations.models import Organization, Plan
from squarelet.users.forms import NewOrganizationModelChoiceField


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

    def __init__(self, *args, plan=None, user=None, **kwargs):
        """
        Initialize the form with plan and user context.

        Args:
            plan: The Plan instance being purchased
            user: The authenticated User instance
        """
        # Don't pass instance to parent - we handle organization differently
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)

        self.plan = plan
        self.user = user
        self.fields["stripe_token"].required = False

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

            # Exclude organizations already subscribed to this plan
            if self.plan:
                subscribed_orgs = Organization.objects.filter(
                    subscriptions__plan=self.plan,
                    subscriptions__cancelled=False,
                )
                base_queryset = base_queryset.exclude(pk__in=subscribed_orgs)

            self.fields["organization"].queryset = base_queryset
        else:
            self.fields["organization"].queryset = Organization.objects.none()

    def _configure_payment_method_field(self):
        """Configure payment method choices based on plan"""
        choices = [
            ("new-card", _("Use new card")),
        ]

        # Invoice option only for annual plans
        if self.plan and self.plan.annual:
            choices.append(("invoice", _("Pay by invoice")))

        self.fields["payment_method"].choices = choices

    def _configure_nonprofit_field(self):
        """Show nonprofit field only for Sunlight plans that aren't nonprofit variants"""
        is_nonprofit_variant = self.plan and self.plan.slug.startswith(
            "sunlight-nonprofit-"
        )
        if not self.plan or not self.plan.is_sunlight_plan or is_nonprofit_variant:
            del self.fields["is_nonprofit"]

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
            card = org.customer().card
            if card:
                org_cards[str(org.pk)] = {
                    "last4": card.last4,
                    "brand": card.brand,
                }

        return org_cards

    def get_plan_data(self):
        """
        Build plan data for frontend JavaScript.

        Returns:
            dict: Plan information for JS
        """
        if not self.plan:
            return {}

        data = {
            "annual": self.plan.annual,
            "is_sunlight_plan": self.plan.is_sunlight_plan,
            "base_price": self.plan.base_price,
            "price_per_user": self.plan.price_per_user,
            "minimum_users": self.plan.minimum_users,
        }

        # Add nonprofit plan pricing if available
        if self.plan.is_sunlight_plan:
            nonprofit_slug = self.plan.nonprofit_variant_slug
            if nonprofit_slug:
                try:
                    nonprofit_plan = Plan.objects.get(slug=nonprofit_slug)
                    data["nonprofit_base_price"] = nonprofit_plan.base_price
                    data["nonprofit_price_per_user"] = nonprofit_plan.price_per_user
                    data["has_nonprofit_variant"] = True
                except Plan.DoesNotExist:
                    data["has_nonprofit_variant"] = False
            else:
                data["has_nonprofit_variant"] = False
        else:
            data["has_nonprofit_variant"] = False

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

    def clean_is_nonprofit(self):
        """Validate nonprofit checkbox is only used for Sunlight plans"""
        is_nonprofit = self.cleaned_data.get("is_nonprofit", False)

        if is_nonprofit and self.plan and not self.plan.is_sunlight_plan:
            raise forms.ValidationError(
                _("Non-profit discount is only available for Sunlight plans")
            )

        return is_nonprofit

    def clean(self):
        """
        Cross-field validation for payment method and organization.
        """
        data = super().clean()

        organization = data.get("organization")
        payment_method = data.get("payment_method")
        stripe_token = data.get("stripe_token")

        # Validate payment method matches available options
        if payment_method == "existing-card":
            if organization and organization != "new":
                if not organization.customer().card:
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
            if self.plan and not self.plan.annual:
                self.add_error(
                    "payment_method",
                    _("Invoice payment is only available for annual plans."),
                )

        return data

    def get_selected_plan(self):
        """
        Get the actual plan to subscribe to, handling nonprofit substitution.

        Returns:
            Plan instance (may be nonprofit variant if is_nonprofit is True)
        """
        if not self.is_valid():
            return self.plan

        is_nonprofit = self.cleaned_data.get("is_nonprofit", False)

        if is_nonprofit and self.plan and self.plan.is_sunlight_plan:
            nonprofit_slug = self.plan.nonprofit_variant_slug
            if nonprofit_slug:
                try:
                    return Plan.objects.get(slug=nonprofit_slug)
                except Plan.DoesNotExist:
                    pass

        return self.plan

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
            dict with organization, plan, payment_method, and stripe_token
        """
        organization = self.get_or_create_organization(user)
        selected_plan = self.get_selected_plan()

        return {
            "organization": organization,
            "plan": selected_plan,
            "payment_method": self.cleaned_data.get("payment_method"),
            "stripe_token": self.cleaned_data.get("stripe_token"),
        }
