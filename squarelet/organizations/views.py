# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

# Standard Library
from datetime import datetime

# Local
from .forms import AddMemberForm, BuyRequestsForm, ManageMembersForm, UpdateForm
from .mixins import OrganizationAdminMixin
from .models import Invitation, Membership, Organization, ReceiptEmail
from .tasks import (
    push_update_add_member,
    push_update_organization,
    push_update_remove_member,
)


class Detail(DetailView):
    model = Organization

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["is_admin"] = self.object.is_admin(self.request.user)
        return context


class List(ListView):
    model = Organization

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(individual=False)
            .get_viewable(self.request.user)
        )


class Update(OrganizationAdminMixin, UpdateView):
    model = Organization
    form_class = UpdateForm

    def form_valid(self, form):
        with transaction.atomic():
            organization = self.object
            organization.private = form.cleaned_data["private"]
            organization.set_subscription(
                token=form.cleaned_data["stripe_token"],
                plan=form.cleaned_data["plan"],
                max_users=form.cleaned_data.get("max_users"),
            )
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            organization.save()
            transaction.on_commit(
                lambda: push_update_organization.delay(organization.pk)
            )
        messages.success(self.request, "Organization Updated")
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["STRIPE_PUB_KEY"] = settings.STRIPE_PUB_KEY
        return context

    def get_initial(self):
        return {
            "plan": self.object.plan,
            "max_users": self.object.max_users,
            "private": self.object.private,
            "receipt_emails": "\n".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class Create(LoginRequiredMixin, CreateView):
    model = Organization
    fields = ("name",)

    def form_valid(self, form):
        """The organization creator is automatically a member and admin of the
        organization"""
        with transaction.atomic():
            response = super().form_valid(form)
            organization = self.object
            # add creator to the organization as an admin by default
            Membership.objects.create(
                user=self.request.user, organization=organization, admin=True
            )
            # add the creators email as a receipt recipient by default
            ReceiptEmail.objects.create(
                organization=organization, email=self.request.user.email
            )
            transaction.on_commit(
                lambda: (
                    push_update_organization.delay(organization.pk),
                    # wait 5 seconds to add the member to give time for organization
                    # to be saved
                    push_update_add_member.apply_async(
                        args=[organization.pk, self.request.user.pk], countdown=5
                    ),
                )
            )
        return response


class AddMember(OrganizationAdminMixin, DetailView, FormView):
    model = Organization
    form_class = AddMemberForm
    template_name = "organizations/organization_form.html"
    # XXX no addingmembers to individual organizations

    def form_valid(self, form):
        """Create an invitation and send it to the given email address"""
        organization = self.get_object()
        invitation = Invitation.objects.create(
            organization=organization, email=form.cleaned_data["email"]
        )
        invitation.send()
        messages.success(self.request, "Invitation sent")
        return redirect(organization)


class BuyRequests(OrganizationAdminMixin, UpdateView):
    model = Organization
    form_class = BuyRequestsForm

    def form_valid(self, form):
        """Create an invitation and send it to the given email address"""
        organization = self.object
        if form.cleaned_data["save_card"]:
            organization.save_card(form.cleaned_data["stripe_token"])
        organization.buy_requests(
            form.cleaned_data["number_requests"], form.cleaned_data["stripe_token"]
        )
        messages.success(self.request, "Requests bought")
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["STRIPE_PUB_KEY"] = settings.STRIPE_PUB_KEY
        return context


class ManageMembers(OrganizationAdminMixin, UpdateView):
    model = Organization
    form_class = ManageMembersForm
    template_name = "organizations/organization_managemembers.html"

    def form_valid(self, form):
        """Edit members admin status or remove them from the organization"""

        organization = self.object
        remove_user_ids = []

        with transaction.atomic():
            for membership in organization.memberships.all():
                if form.cleaned_data[f"remove-{membership.user_id}"]:
                    membership.delete()
                    remove_user_ids.append(membership.user_id)
                elif (
                    form.cleaned_data[f"admin-{membership.user_id}"] != membership.admin
                ):
                    membership.admin = form.cleaned_data[f"admin-{membership.user_id}"]
                    membership.save()
            transaction.on_commit(
                lambda: [
                    push_update_remove_member.delay(organization.pk, user_id)
                    for user_id in remove_user_ids
                ]
            )

        messages.success(self.request, "Members updated")
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        context["users"] = [
            (u, form[f"admin-{u.pk}"], form[f"remove-{u.pk}"])
            for u in self.object.users.all()
        ]
        return context


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
        with transaction.atomic():
            invitation.user = self.request.user
            invitation.save()
            Membership.objects.create(
                organization=invitation.organization, user=self.request.user
            )
            transaction.on_commit(
                lambda: push_update_add_member(
                    invitation.organization.pk, self.request.user.pk
                )
            )
        messages.success(self.request, "Invitation accepted")
        return redirect(invitation.organization)
