# Django
from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import DetailView

# Third Party
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.organizations.denylist_domains import DENYLIST_DOMAINS
from squarelet.organizations.forms import DomainActionForm
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Organization, OrganizationEmailDomain


class ManageDomains(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_domains"
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managedomains.html"

    def get_available_domains(self):
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

    def get_context_data(self, **kwargs):
        self.organization = self.get_object()

        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user
        context["domains"] = self.organization.domains.all()
        context["available_domains"] = self.get_available_domains()
        return context

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        form = DomainActionForm(
            request.POST,
            available_domains=self.get_available_domains(),
            organization=self.organization,
        )

        # Render errors into alerts on the page since we're
        # we're not rendering per-field errors in the form.
        if not form.is_valid():
            for error in form.errors.get("__all__", []):
                messages.error(request, error)
            for field, errors in form.errors.items():
                if field != "__all__":
                    for error in errors:
                        messages.error(request, error)
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Since the form is valid, we know we're either handling
        # the add or remove action. Any other actions will be
        # caught as errors and returned above.
        handlers = {
            DomainActionForm.ACTION_ADD: self.handle_add_domain,
            DomainActionForm.ACTION_REMOVE: self.handle_remove_domain,
        }
        return handlers[form.cleaned_data["action"]](request, form)

    def handle_add_domain(self, request, form):
        # Create a new OrganizationEmailDomain entry
        # with the provided domain and organization
        domain = form.cleaned_data["domain"]
        OrganizationEmailDomain.objects.create(
            organization=self.organization, domain=domain
        )
        messages.success(request, f"The domain {domain} was added successfully.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def handle_remove_domain(self, request, form):
        # `domain_entry` is the OrganizationEmailDomain instance to delete
        domain_entry = form.cleaned_data["domain_entry"]
        domain_entry.delete()
        # `domain` is just the string of the domain name for messaging purposes
        domain = form.cleaned_data["domain"]
        messages.success(request, f"The domain {domain} was removed successfully.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)
