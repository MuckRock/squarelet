# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

# Local
from .forms import (
    AddMemberForm,
    BuyRequestsForm,
    ManageInvitationsForm,
    ManageMembersForm,
    UpdateForm,
)
from .mixins import OrganizationAdminMixin
from .models import Invitation, Membership, Organization, ReceiptEmail


class Detail(DetailView):
    model = Organization

    def can_join(self):
        """Can the current user request to join this organization?"""
        return self.request.user.is_authenticated and not self.object.has_member(
            self.request.user
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["is_admin"] = self.object.is_admin(self.request.user)
        context["can_join"] = self.can_join()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.can_join():
            self.object.invitations.create(
                email=request.user.email, user=request.user, request=True
            )
            messages.success(request, _("Request to join the organization sent!"))
            # XXX notify the admins via email
        return redirect(self.object)


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
        organization = self.object
        organization.private = form.cleaned_data["private"]
        organization.set_subscription(
            token=form.cleaned_data["stripe_token"],
            plan=form.cleaned_data["plan"],
            max_users=form.cleaned_data.get("max_users"),
        )
        organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
        organization.save()
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
        return response


class AddMember(OrganizationAdminMixin, DetailView, FormView):
    model = Organization
    form_class = AddMemberForm
    template_name = "organizations/organization_form.html"

    def dispatch(self, request, *args, **kwargs):
        """Check max users"""
        organization = self.get_object()
        if organization.user_count() >= organization.max_users:
            messages.error(
                request, "You need to increase your max users to invite another member"
            )
            return self.get(request, *args, **kwargs)
        else:
            return super(AddMember, self).dispatch(request, *args, **kwargs)

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

        with transaction.atomic():
            for membership in organization.memberships.all():
                if form.cleaned_data[f"remove-{membership.user_id}"]:
                    membership.delete()
                elif (
                    form.cleaned_data[f"admin-{membership.user_id}"] != membership.admin
                ):
                    membership.admin = form.cleaned_data[f"admin-{membership.user_id}"]
                    membership.save()

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

    def get_queryset(self):
        return super().get_pending()

    def post(self, request, *args, **kwargs):
        """Accept the invitation"""
        invitation = self.get_object()
        invitation.accept(self.request.user)
        messages.success(self.request, "Invitation accepted")
        return redirect(invitation.organization)


class ManageInvitations(OrganizationAdminMixin, UpdateView):
    model = Organization
    form_class = ManageInvitationsForm
    template_name = "organizations/invitation_list.html"

    def get_context_data(self, **kwargs):
        # pylint: disable=arguments-differ
        context = super().get_context_data(**kwargs)
        form = context["form"]
        context["requested_invitations"] = [
            (i, form[f"accept-{i.pk}"]) for i in self.object.invitations.get_requested()
        ]
        context["pending_invitations"] = [
            (i, form[f"remove-{i.pk}"]) for i in self.object.invitations.get_pending()
        ]
        context["accepted_invitations"] = self.object.invitations.get_accepted()
        return context

    def form_valid(self, form):
        """Revoke selected invitations"""
        organization = self.object

        with transaction.atomic():
            if form.cleaned_data["action"] == "revoke":
                for invitation in organization.invitations.get_pending():
                    if form.cleaned_data[f"remove-{invitation.id}"]:
                        invitation.delete()
                messages.success(self.request, "Invitations revoked")
            elif form.cleaned_data["action"] == "accept":
                for invitation in organization.invitations.get_requested():
                    if form.cleaned_data[f"accept-{invitation.id}"]:
                        invitation.accept()
        return redirect(organization)
