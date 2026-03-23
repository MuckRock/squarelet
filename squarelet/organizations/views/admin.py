# Django
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.shortcuts import redirect
from django.views.generic.edit import FormView

# Squarelet
from squarelet.organizations.forms import MergeForm


class Merge(PermissionRequiredMixin, FormView):
    """View to merge agencies together"""

    form_class = MergeForm
    template_name = "organizations/organization_merge.html"
    permission_required = "organizations.merge_organization"

    def get_initial(self):
        """Set initial choice based on get parameter"""
        initial = super().get_initial()
        if "bad_org" in self.request.GET:
            initial["bad_org"] = self.request.GET["bad_org"]
        return initial

    def form_valid(self, form):
        """Confirm and merge"""
        if form.cleaned_data["confirmed"]:
            good = form.cleaned_data["good_organization"]
            bad = form.cleaned_data["bad_organization"]
            try:
                good.merge(bad, self.request.user)
            except ValueError as exc:
                messages.error(self.request, f"There was an error: {exc.args[0]}")
                return redirect("organizations:merge")

            messages.success(self.request, f"Merged {bad} into {good}!")
            return redirect("organizations:merge")
        else:
            initial = {
                "good_organization": form.cleaned_data["good_organization"],
                "bad_organization": form.cleaned_data["bad_organization"],
            }
            form = self.form_class(confirmed=True, initial=initial)
            return self.render_to_response(self.get_context_data(form=form))

    def form_invalid(self, form):
        """Something went wrong"""
        messages.error(self.request, form.errors)
        return redirect("organizations:merge")

    def handle_no_permission(self):
        """What to do if the user does not have permisson to view this page"""
        messages.error(self.request, "You do not have permission to view this page")
        return redirect("home")
