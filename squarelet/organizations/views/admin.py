# Django
from django.contrib import messages
from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin,
)
from django.db import transaction
from django.shortcuts import redirect
from django.views.generic import CreateView
from django.views.generic.edit import FormView

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from fuzzywuzzy import fuzz, process

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.forms import MergeForm
from squarelet.organizations.models import Organization


class Create(LoginRequiredMixin, CreateView):
    model = Organization
    template_name_suffix = "_create_form"
    fields = ("name",)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.helper = FormHelper()
        form.helper.layout = Layout(
            Field(
                "name",
                css_class="_cls-nameInput",
                wrapper_class="_cls-field",
                template="account/field.html",
                placeholder="New organization name",
            )
        )
        form.helper.form_tag = False
        return form

    @transaction.atomic
    def form_valid(self, form):
        """The organization creator is automatically a member and admin of the
        organization"""

        # looking for matching organizations first
        if not self.request.POST.get("force"):
            name = form.cleaned_data["name"]

            all_organizations = Organization.objects.filter(individual=False)
            matching_orgs = process.extractBests(
                name,
                {o: o.name for o in all_organizations},
                limit=10,
                scorer=fuzz.partial_ratio,
                score_cutoff=83,
            )
            matching_orgs = [org for _, _, org in matching_orgs]

            if matching_orgs:
                return self.render_to_response(
                    self.get_context_data(matching_orgs=matching_orgs)
                )

        # no matching orgs, just create
        organization = form.save()
        organization.add_creator(self.request.user)
        organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=self.request.user,
            to_plan=organization.plan,
            to_max_users=organization.max_users,
        )
        return redirect(organization)


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
