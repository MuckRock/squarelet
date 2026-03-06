# Django
from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import DetailView

# Third Party
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.organizations.denylist_domains import DENYLIST_DOMAINS
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Organization, OrganizationEmailDomain


class ManageDomains(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_domains"
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managedomains.html"

    def _get_available_domains(self):
        """Get domains from the admin's verified emails, excluding denylist
        and already-added domains."""
        verified_emails = EmailAddress.objects.filter(
            user=self.request.user, verified=True
        ).values_list("email", flat=True)
        user_domains = {email.split("@")[1].lower() for email in verified_emails}
        existing_domains = set(
            self.organization.domains.values_list("domain", flat=True)
        )
        return sorted(user_domains - DENYLIST_DOMAINS - existing_domains)

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
        available = self._get_available_domains()

        if domain not in available:
            messages.error(
                request,
                "Invalid domain. Please select a domain from your verified emails.",
            )
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        OrganizationEmailDomain.objects.create(
            organization=self.organization, domain=domain
        )
        messages.success(request, f"The domain {domain} was added successfully.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def _handle_remove_domain(self, request):
        domain = request.POST.get("domain", "").strip().lower()

        try:
            domain_entry = OrganizationEmailDomain.objects.get(
                organization=self.organization, domain=domain
            )
            domain_entry.delete()
            messages.success(request, f"The domain {domain} was removed successfully.")
        except OrganizationEmailDomain.DoesNotExist:
            messages.error(
                request,
                f"The domain {domain} was not found or has already been removed.",
            )

        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def get_context_data(self, **kwargs):
        self.organization = self.get_object()

        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user
        context["domains"] = self.organization.domains.all()
        context["available_domains"] = self._get_available_domains()
        return context

    def _bad_call(self, request):
        messages.error(request, "An unexpected error occurred.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)
