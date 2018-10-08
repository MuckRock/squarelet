
# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http.response import HttpResponseRedirect
from django.shortcuts import redirect
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

# Local
from .forms import AddMemberForm, UpdateForm
from .mixins import OrganizationAdminMixin
from .models import Invitation, Organization, OrganizationMembership


class Detail(DetailView):
    model = Organization

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["is_admin"] = self.object.is_admin(self.request.user)
        return context


class List(ListView):
    model = Organization

    def get_queryset(self):
        return super().get_queryset().get_viewable(self.request.user)


class Update(OrganizationAdminMixin, UpdateView):
    model = Organization
    form_class = UpdateForm

    def form_valid(self, form):
        self.object.set_subscription(
            token=form.cleaned_data["stripe_token"],
            org_type=form.cleaned_data["org_type"],
            max_users=form.cleaned_data.get("max_users"),
        )
        messages.success(self.request, "Organization Updated")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["STRIPE_PUB_KEY"] = settings.STRIPE_PUB_KEY
        return context


class Create(LoginRequiredMixin, CreateView):
    model = Organization
    fields = ("name",)

    def form_valid(self, form):
        """The organization creator is automatically a member and admin of the
        organization"""
        response = super().form_valid(form)
        OrganizationMembership.objects.create(
            user=self.request.user, organization=self.object, admin=True
        )
        return response


class AddMember(OrganizationAdminMixin, DetailView, FormView):
    model = Organization
    form_class = AddMemberForm
    template_name = "organizations/organization_form.html"

    def form_valid(self, form):
        """Create an invitation and send it to the given email address"""
        organization = self.get_object()
        invitation = Invitation.objects.create(
            organization=organization, email=form.cleaned_data["email"]
        )
        invitation.send()
        messages.success(self.request, "Invitation sent")
        return redirect(organization)


class InvitationAccept(LoginRequiredMixin, DetailView):
    model = Invitation
    slug_field = "uuid"
    slug_url_kwarg = "uuid"

    def post(self, request, *args, **kwargs):
        """Accept the invitation"""
        invitation = self.get_object()
        if invitation.user is not None:
            messages.error(self.request, "That invitation has already been accepted")
            return redirect(self.request.user)
        invitation.user = self.request.user
        invitation.save()
        OrganizationMembership.objects.create(
            organization=invitation.organization, user=self.request.user
        )
        messages.success(self.request, "Invitation accepted")
        return redirect(invitation.organization)
