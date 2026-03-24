# Django
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import FormView
from django.views.generic.detail import SingleObjectMixin

# Third Party
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.organizations.denylist_domains import DENYLIST_DOMAINS
from squarelet.organizations.forms import DomainActionForm
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Organization, OrganizationEmailDomain


class ManageDomains(OrganizationPermissionMixin, SingleObjectMixin, FormView):
    permission_required = "organizations.can_manage_domains"
    queryset = Organization.objects.filter(individual=False)
    form_class = DomainActionForm
    template_name = "organizations/organization_managedomains.html"

    def dispatch(self, request, *args, **kwargs):
        """Set self.organization at the start of the call chain"""
        # Note: This will execute a DB read for all users, even unpermitted ones.
        self.object = self.get_object()
        self.organization = self.object
        return super().dispatch(request, *args, **kwargs)

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
        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user
        context["domains"] = self.organization.domains.all()
        context["available_domains"] = self.get_available_domains()
        return context

    def get_form_kwargs(self):
        """Sets available domains and organization"""
        kwargs = super().get_form_kwargs()
        kwargs["available_domains"] = self.get_available_domains()
        kwargs["organization"] = self.organization
        return kwargs

    def form_valid(self, form):
        """
        Since the form is valid, we know we're either handling
        the add or remove action. Any other actions will be
        caught as errors and returned above.
        """
        action = form.cleaned_data["action"]
        if action == DomainActionForm.ACTION_ADD:
            # Create a new OrganizationEmailDomain entry
            # with the provided domain and organization
            domain = form.cleaned_data["domain"]
            OrganizationEmailDomain.objects.create(
                organization=self.organization, domain=domain
            )
            messages.success(
                self.request, f"The domain {domain} was added successfully."
            )
        elif action == DomainActionForm.ACTION_REMOVE:
            # `domain_entry` is the OrganizationEmailDomain instance to delete
            domain_entry = form.cleaned_data["domain_entry"]
            domain_entry.delete()
            # `domain` is just the string of the domain name for messaging purposes
            domain = form.cleaned_data["domain"]
            messages.success(
                self.request, f"The domain {domain} was removed successfully."
            )
        return super().form_valid(form)

    def form_invalid(self, form):
        """
        Render errors into alerts on the page since we're
        we're not rendering per-field errors in the form.
        """
        for error in form.errors.get("__all__", []):
            messages.error(self.request, error)
        for field, errors in form.errors.items():
            if field != "__all__":
                for error in errors:
                    messages.error(self.request, error)
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def get_success_url(self):
        return reverse(
            "organizations:manage-domains", kwargs={"slug": self.organization.slug}
        )
