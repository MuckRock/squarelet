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
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
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
from squarelet.core.mixins import AdminLinkMixin
from squarelet.core.utils import mixpanel_event
from squarelet.organizations.choices import ChangeLogReason, StripeAccounts
from squarelet.organizations.forms import AddMemberForm, PaymentForm, UpdateForm
from squarelet.organizations.mixins import IndividualMixin, OrganizationAdminMixin
from squarelet.organizations.models import Charge, Invitation, Membership, Organization
from squarelet.organizations.tasks import handle_charge_succeeded, handle_invoice_failed

# How much to paginate organizations list by
ORG_PAGINATION = 100

logger = logging.getLogger(__name__)


class Detail(AdminLinkMixin, DetailView):
    def get_queryset(self):
        return Organization.objects.filter(individual=False).get_viewable(
            self.request.user
        )

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
        if context.get("is_member"):
            context["users"] = self.object.users.all()
        else:
            context["users"] = self.object.users.filter(memberships__admin=True)
        return context

    def post(self, request, *args, **kwargs):
        self.organization = self.get_object()
        if not self.request.user.is_authenticated:
            return redirect(self.organization)
        is_member = self.organization.has_member(self.request.user)
        if request.POST.get("action") == "join" and not is_member:
            invitation = self.organization.invitations.create(
                email=request.user.email, user=request.user, request=True
            )
            messages.success(request, _("Request to join the organization sent!"))
            invitation.send()
        elif request.POST.get("action") == "leave" and is_member:
            self.request.user.memberships.filter(
                organization=self.organization
            ).delete()
            messages.success(request, _("You have left the organization"))
            mixpanel_event(
                request,
                "Left Organization",
                {"Name": self.organization.name, "UUID": str(self.organization.uuid)},
            )
        return redirect(self.organization)


class List(ListView):
    model = Organization
    paginate_by = ORG_PAGINATION

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(individual=False)
            .get_viewable(self.request.user)
        )


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
            .order_by("pos", "slug")
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
        old_plan = organization.plan
        old_users = organization.max_users
        new_plan = form.cleaned_data.get("plan")
        try:
            organization.set_subscription(
                token=form.cleaned_data["stripe_token"],
                plan=new_plan,
                max_users=form.cleaned_data.get("max_users"),
                user=self.request.user,
            )
        except stripe.error.StripeError as exc:
            messages.error(self.request, "Payment error: {}".format(exc.user_message))
        else:
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            messages.success(
                self.request,
                _("Plan Updated")
                if organization.individual
                else _("Organization Updated"),
            )
            mixpanel_event(
                self.request,
                "Organization Subscription Changed",
                {
                    "Name": organization.name,
                    "UUID": str(organization.uuid),
                    "Old Plan": old_plan.name if old_plan else "Free",
                    "New Plan": new_plan.name if new_plan else "Free",
                    "Old Users": old_users,
                    "New Users": form.cleaned_data.get("max_users", 1),
                },
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
        organization = form.save()
        organization.add_creator(self.request.user)
        organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=self.request.user,
            to_plan=organization.plan,
            to_max_users=organization.max_users,
        )
        mixpanel_event(
            self.request,
            "Create Organization",
            {
                "Name": organization.name,
                "UUID": str(organization.uuid),
                "Plan": organization.plan.name if organization.plan else "Free",
                "Max Users": organization.max_users,
                "Sign Up": False,
            },
        )
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
            invite = Invitation.objects.get_open().get(
                pk=inviteid, organization=self.organization
            )
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
        def accept_invite(invite):
            invite.accept()
            mixpanel_event(
                request,
                "Invitation Accepted by Admin",
                {
                    "Organization Name": invite.organization.name,
                    "Organization UUID": str(invite.organization.uuid),
                    "User UUID": str(invite.user.uuid),
                    "User Username": invite.user.username,
                    "User Name": invite.user.name,
                    "User Email": invite.user.email,
                },
            )

        return self._handle_invite(request, accept_invite, "Invitation accepted")

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
        def remove_user(membership):
            membership.delete()
            mixpanel_event(
                request,
                "User Removed",
                {
                    "Organization Name": membership.organization.name,
                    "Organization UUID": str(membership.organization.uuid),
                    "User UUID": str(membership.user.uuid),
                    "User Username": membership.user.username,
                    "User Name": membership.user.name,
                    "User Email": membership.user.email,
                },
            )

        return self._handle_user(request, remove_user, "Removed user")

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
            mixpanel_event(
                request,
                "Invitation Accepted",
                {
                    "Name": invitation.organization.name,
                    "UUID": str(invitation.organization.uuid),
                },
            )
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


@method_decorator(xframe_options_sameorigin, name="dispatch")
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
    # XXX handle webhooks for presspass ?
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        if settings.STRIPE_WEBHOOK_SECRETS[StripeAccounts.muckrock]:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRETS[StripeAccounts.muckrock],
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
