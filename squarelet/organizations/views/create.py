# Django
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView

# Third Party
from allauth.account.utils import has_verified_email

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.forms import CreateForm
from squarelet.organizations.models import Organization


class Create(LoginRequiredMixin, CreateView):
    model = Organization
    form_class = CreateForm
    template_name = "organizations/organization_create_form.html"

    def get_next_url(self):
        """The local URL to return to after creating, or None if absent or unsafe."""
        url = self.request.POST.get("next") or self.request.GET.get("next")
        if url and url_has_allowed_host_and_scheme(
            url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return url
        return None

    def get(self, request, *args, **kwargs):
        if not has_verified_email(request.user):
            request.session["next_url"] = request.get_full_path()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["next_url"] = self.get_next_url()
        return context

    @transaction.atomic
    def form_valid(self, form):
        """The organization creator is automatically a member and admin"""
        if not has_verified_email(self.request.user):
            form.add_error(
                None,
                _(
                    "You must verify your email address before creating "
                    "an organization."
                ),
            )
            return self.form_invalid(form)
        organization = form.save()
        organization.add_creator(self.request.user)
        organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=self.request.user,
            to_plan=organization.get_plans().first(),
            to_max_users=organization.max_users,
        )
        return redirect(self.get_next_url() or organization)
