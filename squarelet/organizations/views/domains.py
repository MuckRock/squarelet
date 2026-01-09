# Django
from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import DetailView

# Standard Library
import re

# Squarelet
from squarelet.organizations.denylist_domains import DENYLIST_DOMAINS
from squarelet.organizations.mixins import VerifiedJournalistMixin
from squarelet.organizations.models import Organization, OrganizationEmailDomain


class ManageDomains(VerifiedJournalistMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managedomains.html"

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        actions = {
            "adddomain": self._handle_add_domain,
            "removedomain": self._handle_remove_domain,
        }
        action = request.POST.get("action")
        if action in actions:
            return actions[action](request)
        return self._bad_call(request)

    def _handle_add_domain(self, request):
        domain = request.POST.get("domain", "").strip().lower()

        # Validate domain format
        if not re.match(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$", domain):
            messages.error(
                request, "Invalid domain format. Please enter a valid domain."
            )
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Check for blacklisted domain
        if domain in DENYLIST_DOMAINS:
            messages.error(request, f"The domain {domain} is not allowed.")
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Prevent duplicates
        if OrganizationEmailDomain.objects.filter(
            organization=self.organization, domain=domain
        ).exists():
            messages.error(request, f"The domain {domain} is already added.")
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Add the domain
        OrganizationEmailDomain.objects.create(
            organization=self.organization, domain=domain
        )
        messages.success(request, f"The domain {domain} was added successfully.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def _handle_remove_domain(self, request):
        domain = request.POST.get("domain", "").strip().lower()

        # Check if domain exists
        try:
            domain_entry = OrganizationEmailDomain.objects.get(
                organization=self.organization, domain=domain
            )

            # Only delete if domain exists
            domain_entry.delete()
            messages.success(request, f"The domain {domain} was removed successfully.")
        except OrganizationEmailDomain.DoesNotExist:
            # Provide a more detailed message in case the domain doesn't exist
            messages.error(
                request,
                f"The domain {domain} was not found or has already been removed.",
            )

        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def get_context_data(self, **kwargs):
        self.organization = self.get_object()

        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user

        # Use 'domains' related_name for your OrganizationEmailDomain model
        context["domains"] = (
            self.organization.domains.all()
        )  # Corrected field to 'domains'
        return context

    def _bad_call(self, request):
        # Handle unexpected actions
        messages.error(request, "An unexpected error occurred.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)
