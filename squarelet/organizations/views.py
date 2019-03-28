# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Value as V
from django.db.models.functions import Lower, StrIndex
from django.http import JsonResponse
from django.http.response import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DetailView, ListView, UpdateView

# Standard Library
import json
import logging
import sys

# Third Party
import stripe
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout

# Squarelet
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.mixins import AdminLinkMixin

# Local
from .forms import AddMemberForm, PaymentForm, UpdateForm
from .mixins import IndividualMixin, OrganizationAdminMixin
from .models import Charge, Invitation, Membership, Organization, Plan
from .tasks import handle_charge_succeeded, handle_invoice_failed

# How much to paginate organizations list by
ORG_PAGINATION = 100

logger = logging.getLogger(__name__)


class Detail(AdminLinkMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context["is_admin"] = self.object.has_admin(self.request.user)
            context["is_member"] = self.object.has_member(self.request.user)

            context["requested_invite"] = self.request.user.invitations.filter(
                organization=self.object
            ).get_requested()
            if context["is_admin"]:
                context[
                    "invite_count"
                ] = self.object.invitations.get_requested().count()
        return context

    def post(self, request, *args, **kwargs):
        self.organization = self.get_object()
        if not self.request.user.is_authenticated:
            return redirect(self.organization)
        is_member = self.organization.has_member(self.request.user)
        if request.POST.get("action") == "join" and not is_member:
            self.organization.invitations.create(
                email=request.user.email, user=request.user, request=True
            )
            messages.success(request, _("Request to join the organization sent!"))
            send_mail(
                subject=_(f"{request.user} has requested to join {self.organization}"),
                template="organizations/email/join_request.html",
                organization=self.organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={"joiner": request.user},
            )
        elif request.POST.get("action") == "leave" and is_member:
            self.request.user.memberships.filter(
                organization=self.organization
            ).delete()
            messages.success(request, _("You have left the organization"))
        return redirect(self.organization)


class List(ListView):
    model = Organization
    paginate_by = ORG_PAGINATION

    def get_queryset(self):
        orgs = super().get_queryset().filter(individual=False)
        return orgs.get_viewable(self.request.user)


def autocomplete(request):
    # This should be replaced by a real API
    query = request.GET.get("q")
    page = request.GET.get("page")
    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1

    orgs = Organization.objects.filter(individual=False).get_viewable(request.user)
    if query:
        # Prioritize showing things that start with query
        orgs = (
            orgs.filter(name__icontains=query)
            .annotate(pos=StrIndex(Lower("name"), Lower(V(query))))
            .order_by("pos")
        )

    data = {
        "data": [
            {"name": o.name, "slug": o.slug, "avatar": o.avatar_url}
            for o in orgs[((page - 1) * ORG_PAGINATION) : (page * ORG_PAGINATION)]
        ]
    }
    return JsonResponse(data)


class UpdateSubscription(OrganizationAdminMixin, UpdateView):
    queryset = Organization.objects.filter(individual=False)
    form_class = PaymentForm

    def form_valid(self, form):
        organization = self.object
        try:
            organization.set_subscription(
                token=form.cleaned_data["stripe_token"],
                plan=form.cleaned_data["plan"],
                max_users=form.cleaned_data.get("max_users"),
            )
        except stripe.error.StripeError as exc:
            messages.error(self.request, "Payment error: {}".format(exc.user_message))
        else:
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            organization.save()
            messages.success(
                self.request,
                _("Plan Updated")
                if organization.individual
                else _("Organization Updated"),
            )
        return redirect(organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["failed_receipt_emails"] = self.object.receipt_emails.filter(
            failed=True
        )
        return context

    def get_initial(self):
        return {
            "plan": self.object.plan,
            "max_users": self.object.max_users,
            "receipt_emails": "\n".join(
                r.email for r in self.object.receipt_emails.all()
            ),
        }


class IndividualUpdateSubscription(IndividualMixin, UpdateSubscription):
    """Subclass to update subscriptions for individual organizations"""


class Update(OrganizationAdminMixin, UpdateView):
    queryset = Organization.objects.filter(individual=False)
    form_class = UpdateForm


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
        free_plan = Plan.objects.get(slug="free")
        organization = form.save(commit=False)
        organization.plan = free_plan
        organization.next_plan = free_plan
        organization.save()
        organization.add_creator(self.request.user)
        return redirect(organization)


class ManageMembers(OrganizationAdminMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managemembers.html"

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        actions = {
            "addmember": self._handle_add_member,
            "revokeinvite": self._handle_revoke_invite,
            "acceptinvite": self._handle_accept_invite,
            "rejectinvite": self._handle_reject_invite,
            "makeadmin": self._handle_makeadmin_user,
            "removeuser": self._handle_remove_user,
        }
        try:
            return actions[request.POST["action"]](request)
        except KeyError:
            return self._bad_call(request)

    def _handle_add_member(self, request):
        addmember_form = AddMemberForm(request.POST)
        if not addmember_form.is_valid():
            # Ensure the email is valid
            messages.error(request, "Please enter a valid email address")
        else:
            # Ensure the org has capacity
            if self.organization.user_count() >= self.organization.max_users:
                messages.error(
                    request,
                    "You need to increase your max users to invite another member",
                )
            else:
                # Create an invitation and send it to the given email address
                invitation = Invitation.objects.create(
                    organization=self.organization,
                    email=addmember_form.cleaned_data["email"],
                )
                invitation.send()
                messages.success(self.request, "Invitation sent")
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_invite(self, request, invite_fn, success_message):
        try:
            inviteid = request.POST.get("inviteid")
            invite = Invitation.objects.get(pk=inviteid, organization=self.organization)
            invite_fn(invite)
            messages.success(self.request, success_message)
        except Invitation.DoesNotExist:
            return self._bad_call(request)
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_revoke_invite(self, request):
        return self._handle_invite(
            request, lambda invite: invite.reject(), "Invitation revoked"
        )

    def _handle_accept_invite(self, request):
        return self._handle_invite(
            request, lambda invite: invite.accept(), "Invitation accepted"
        )

    def _handle_reject_invite(self, request):
        return self._handle_invite(
            request, lambda invite: invite.reject(), "Invitation rejected"
        )

    def _handle_user(self, request, membership_fn, success_message):
        try:
            userid = request.POST.get("userid")
            membership = self.organization.memberships.get(user_id=userid)
            membership_fn(membership)
            messages.success(self.request, success_message)
        except Membership.DoesNotExist:
            return self._bad_call(request)
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_makeadmin_user(self, request):
        admin_param = request.POST.get("admin")
        if admin_param == "true":
            set_admin = True
        elif admin_param == "false":
            set_admin = False
        else:
            return self._bad_call(request)

        def handle_make_admin(membership):
            membership.admin = set_admin
            membership.save()

        return self._handle_user(
            request,
            handle_make_admin,
            "Made an admin" if set_admin else "Made not an admin",
        )

    def _handle_remove_user(self, request):
        return self._handle_user(
            request, lambda membership: membership.delete(), "Removed user"
        )

    def _bad_call(self, request):
        messages.error(self.request, "An unexpected error occurred")
        return redirect("organizations:manage-members", slug=self.organization.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user
        context["members"] = self.object.memberships.select_related("user").order_by(
            "user__created_at"
        )
        context["requested_invitations"] = self.object.invitations.get_requested()
        context["pending_invitations"] = self.object.invitations.get_pending()
        return context


class InvitationAccept(LoginRequiredMixin, DetailView):
    queryset = Invitation.objects.get_pending()
    slug_field = "uuid"
    slug_url_kwarg = "uuid"

    def post(self, request, *args, **kwargs):
        """Accept the invitation"""
        invitation = self.get_object()
        action = request.POST.get("action")
        if action == "accept":
            invitation.accept(self.request.user)
            messages.success(self.request, "Invitation accepted")
            return redirect(invitation.organization)
        elif action == "reject":
            invitation.reject()
            messages.warning(self.request, "Invitation rejected")
            return redirect(request.user)
        else:
            messages.error(self.request, "Invalid choice")
            return redirect(request.user)


class Receipts(OrganizationAdminMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_receipts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["charges"] = self.object.charges.all()
        return context


class IndividualReceipts(IndividualMixin, Receipts):
    """Subclass to view individual's receipts"""


class ChargeDetail(UserPassesTestMixin, DetailView):
    queryset = Charge.objects.all()
    template_name = "organizations/email/receipt.html"

    def test_func(self):
        return self.get_object().organization.has_admin(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subject"] = "Receipt"
        return context


@csrf_exempt
def stripe_webhook(request):
    """Handle webhooks from stripe"""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        if settings.STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        else:
            event = json.loads(request.body)

        event_type = event["type"]
    except (TypeError, ValueError, SyntaxError) as exception:
        logger.error(
            "Stripe Webhook: Error parsing JSON: %s", exception, exc_info=sys.exc_info()
        )
        return HttpResponseBadRequest()
    except KeyError as exception:
        logger.error(
            "Stripe Webhook: Unexpected structure: %s in %s",
            exception,
            event,
            exc_info=sys.exc_info(),
        )
        return HttpResponseBadRequest()
    except stripe.error.SignatureVerificationError as exception:
        logger.error(
            "Stripe Webhook: Signature Verification Error: %s",
            sig_header,
            exc_info=sys.exc_info(),
        )
        return HttpResponseBadRequest()
    # If we've made it this far, then the webhook message was successfully sent!
    # Now it's up to us to act on it.
    success_msg = (
        "Received Stripe webhook\n"
        "\tfrom:\t%(address)s\n"
        "\ttype:\t%(type)s\n"
        "\tdata:\t%(data)s\n"
    ) % {"address": request.META["REMOTE_ADDR"], "type": event_type, "data": event}
    logger.info(success_msg)
    if event_type == "charge.succeeded":
        handle_charge_succeeded.delay(event["data"]["object"])
    elif event_type == "invoice.payment_failed":
        handle_invoice_failed.delay(event["data"]["object"])
    return HttpResponse()
