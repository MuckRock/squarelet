# Django
# Third Party
# Standard Library
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.utils.translation import ugettext_lazy as _
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

# Standard Library
from itertools import chain

# Third Party
# Crispy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from dal import autocomplete

# Local
from .forms import (
    AddMemberForm,
    BuyRequestsForm,
    ManageInvitationsForm,
    ManageMembersForm,
    UpdateForm,
)
from .mixins import OrganizationAdminMixin
from .models import Invitation, Organization, Plan


class Detail(DetailView):
    queryset = Organization.objects.filter(individual=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            context["is_admin"] = self.object.has_admin(self.request.user)
            context["is_member"] = self.object.has_member(self.request.user)

            context["requested_invite"] = self.request.user.invitations.filter(
                organization=self.object, request=True, accepted_at=None
            )
            context["invited"] = self.request.user.invitations.filter(
                organization=self.object, request=False, accepted_at=None
            )
            if context["is_admin"]:
                context["invites"] = self.object.invitations.all()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not self.request.user.is_authenticated:
            return redirect(self.object)
        is_member = self.object.has_member(self.request.user)
        if request.POST.get("action") == "join" and not is_member:
            self.object.invitations.create(
                email=request.user.email, user=request.user, request=True
            )
            messages.success(request, _("Request to join the organization sent!"))
            # XXX notify the admins via email
        elif request.POST.get("action") == "leave" and is_member:
            membership = self.request.user.memberships.filter(
                organization=self.object
            ).first()
            if membership:
                membership.delete()
            messages.success(request, _("You have left the organization"))
        return redirect(self.object)


class List(ListView):
    model = Organization
    paginate_by = 100

    def get_queryset(self):
        orgs = super().get_queryset().filter(individual=False)
        filter_name = self.request.GET.get("name")
        # self.form = AutocompleteForm(self.request.GET)
        if filter_name:
            orgs = orgs.filter(name__icontains=filter_name)
        return orgs.get_viewable(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["name"] = self.request.GET.get("name", "")
        # context['form'] = self.form
        return context


class Autocomplete(autocomplete.Select2QuerySetView):
    model = Organization

    def get_queryset(self):
        orgs = (
            super()
            .get_queryset()
            .filter(individual=False)
            .get_viewable(self.request.user)
        )
        if self.q:
            # Prioritize showing things that start with query
            orgs1 = orgs.filter(name__istartswith=self.q)
            orgs2 = orgs.filter(name__icontains=self.q).exclude(
                name__istartswith=self.q
            )
            orgs = list(chain(orgs1, orgs2))
        return orgs


class Update(OrganizationAdminMixin, UpdateView):
    queryset = Organization.objects.filter(individual=False)
    form_class = UpdateForm

    def form_valid(self, form):
        organization = self.object
        if "private" in form.cleaned_data:
            organization.private = form.cleaned_data["private"]
        organization.set_subscription(
            token=form.cleaned_data["stripe_token"],
            plan=form.cleaned_data["plan"],
            max_users=form.cleaned_data.get("max_users"),
        )
        organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
        organization.save()
        messages.success(self.request, _("Organization Updated"))
        if organization.individual:
            user = organization.users.first()
            if user:
                return redirect(user)
            else:
                return redirect("index")
        else:
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


class IndividualUpdate(Update):
    """Subclass to update individual organizations"""

    # XXX mixin for indiviual orgs?

    def get_object(self, queryset=None):
        return Organization.objects.get(pk=self.request.user.pk)


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
        # self.fields["name"].widget.attrs.pop("autofocus", None)
        form.helper.form_tag = False
        return form

    @transaction.atomic
    def form_valid(self, form):
        """The organization creator is automatically a member and admin of the
        organization"""
        free_plan = Plan.objects.get(slug="free")
        organization = form.save(commit=False)
        organization.plan = free_plan
        organization.next_plan = free_plan
        organization.save()
        organization.add_creator(self.request.user)
        return redirect(organization)


class AddMember(OrganizationAdminMixin, DetailView, FormView):
    queryset = Organization.objects.filter(individual=False)
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
    queryset = Organization.objects.filter(individual=False)
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


class IndividualBuyRequests(BuyRequests):
    """Subclass to buy requests for individual organizations"""

    def get_object(self, queryset=None):
        return Organization.objects.get(pk=self.request.user.pk)


class ManageMembers(OrganizationAdminMixin, UpdateView):
    queryset = Organization.objects.filter(individual=False)
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
    queryset = Organization.objects.filter(individual=False)
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
    queryset = Organization.objects.filter(individual=False)
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
