# Django
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.views.generic import CreateView

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.forms import CreateForm
from squarelet.organizations.models import Organization


class Create(LoginRequiredMixin, CreateView):
    model = Organization
    form_class = CreateForm
    template_name = "organizations/organization_create_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_verified_email"] = self.request.user.emailaddress_set.filter(
            verified=True
        ).exists()
        return context

    @transaction.atomic
    def form_valid(self, form):
        """The organization creator is automatically a member and admin"""
        organization = form.save()
        organization.add_creator(self.request.user)
        organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=self.request.user,
            to_plan=organization.plan,
            to_max_users=organization.max_users,
        )
        return redirect(organization)
