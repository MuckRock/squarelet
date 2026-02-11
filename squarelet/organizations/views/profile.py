# Django
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, UpdateView

# Squarelet
from squarelet.core.utils import new_action
from squarelet.organizations.forms import ProfileChangeRequestForm, UpdateForm
from squarelet.organizations.mixins import OrganizationPermissionMixin
from squarelet.organizations.models import Organization, ProfileChangeRequest


class Update(OrganizationPermissionMixin, UpdateView):
    permission_required = "organizations.change_organization"
    "Update organization metadata, with some fields requiring staff approval first"

    queryset = Organization.objects.filter(individual=False)
    form_class = UpdateForm
    template_name = "organizations/organization_update.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Create an instance of ProfileChangeRequest for this organization
        profile_change_request = ProfileChangeRequest(
            organization=self.object,
            user=self.request.user,
        )

        context["profile_change_form"] = ProfileChangeRequestForm(
            instance=profile_change_request,
            request=self.request,
        )
        # Include any pending profile change requests
        context["pending_change_requests"] = self.object.profile_change_requests.filter(
            status="pending"
        )
        # Pass permission for reviewing profile changes
        user = self.request.user
        context["can_review_profile_changes"] = user.has_perm(
            "organizations.can_review_profile_changes", self.object
        ) or user.has_perm("organizations.can_review_profile_changes")
        return context

    def form_valid(self, form):
        """Save form and log staff actions with changed fields"""
        response = super().form_valid(form)

        # Log staff action if user is staff and fields changed
        if self.request.user.is_staff and form.changed_data:
            changed_fields = ", ".join(form.changed_data)
            new_action(
                actor=self.request.user,
                verb="updated the profile",
                target=self.object,
                description=f"Changed fields: {changed_fields}",
            )

        return response


class RequestProfileChange(OrganizationPermissionMixin, CreateView):
    """Handle profile change requests for organization fields requiring staff
    approval"""

    permission_required = "organizations.change_organization"
    model = ProfileChangeRequest
    form_class = ProfileChangeRequestForm
    queryset = Organization.objects.filter(individual=False)

    def get_object(self, queryset=None):
        """Get the organization from the URL (used by OrganizationPermissionMixin)"""
        return self.queryset.get(slug=self.kwargs["slug"])

    def get_organization(self):
        """Get the organization from the URL"""
        return self.get_object()

    def get(self, request, *args, **kwargs):
        """Redirect GET requests back to the organization profile page"""
        return redirect("organizations:detail", slug=kwargs["slug"])

    def get_form_kwargs(self):
        """Pass the organization instance and request to the form"""
        kwargs = super().get_form_kwargs()
        organization = self.get_organization()
        if organization:
            # Create a ProfileChangeRequest instance with the organization
            kwargs["instance"] = ProfileChangeRequest(
                organization=organization, user=self.request.user
            )
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        """Save the profile change request"""
        profile_change_request = form.save(commit=False)
        profile_change_request.organization = self.get_organization()
        profile_change_request.user = self.request.user
        profile_change_request.save()

        # Log staff action when editing protected fields
        if self.request.user.is_staff:
            # Get the fields that were changed (non-empty values in the request)
            changed_fields = [
                field
                for field in ProfileChangeRequest.FIELDS
                if getattr(profile_change_request, field)
            ]
            # Also check URL since it's handled separately
            if form.cleaned_data.get("url"):
                changed_fields.append("url")

            if changed_fields:
                new_action(
                    actor=self.request.user,
                    verb="submitted profile change request",
                    action_object=profile_change_request,
                    target=profile_change_request.organization,
                    description=f"Changed fields: {', '.join(changed_fields)}",
                )

        messages.success(
            self.request,
            _(
                "Your profile change request has been submitted and will be "
                "reviewed by staff."
            ),
        )
        return redirect(
            "organizations:update", slug=profile_change_request.organization.slug
        )

    def form_invalid(self, form):
        """Handle invalid form submission"""
        messages.error(
            self.request,
            _(
                "There was an error with your submission. Please check the "
                "form and try again."
            ),
        )
        return redirect("organizations:update", slug=self.kwargs["slug"])


class ReviewProfileChange(View):
    """Handle staff review (accept/reject) of profile change requests"""

    def post(self, request, slug, pk):
        """Accept or reject a profile change request"""
        # Verify user has permission to review profile changes
        has_review_perm = request.user.has_perm(
            "organizations.can_review_profile_changes"
        )
        if not has_review_perm:
            messages.error(
                request,
                _("You do not have permission to review profile change requests."),
            )
            return redirect("organizations:update", slug=slug)

        # Get the profile change request
        try:
            profile_change = ProfileChangeRequest.objects.get(
                pk=pk, organization__slug=slug, status="pending"
            )
        except ProfileChangeRequest.DoesNotExist:
            messages.error(
                request,
                _("Profile change request not found or already processed."),
            )
            return redirect("organizations:update", slug=slug)

        # Get the action from POST data
        action = request.POST.get("action")

        if action == "accept":
            profile_change.accept()

            # Log staff action to activity stream
            new_action(
                actor=request.user,
                verb="accepted profile change request",
                action_object=profile_change,
                target=profile_change.organization,
            )

            messages.success(
                request,
                _("Profile change request has been accepted and applied."),
            )
        elif action == "reject":
            profile_change.reject()

            # Log staff action to activity stream
            new_action(
                actor=request.user,
                verb="rejected profile change request",
                action_object=profile_change,
                target=profile_change.organization,
            )

            messages.success(
                request,
                _("Profile change request has been rejected."),
            )
        else:
            messages.error(
                request,
                _("Invalid action specified."),
            )

        return redirect("organizations:update", slug=slug)
