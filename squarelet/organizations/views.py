# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UserPassesTestMixin,
)
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
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.edit import FormView

# Standard Library
import json
import logging
import re
import sys
from datetime import timedelta

# Third Party
import stripe
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from django_weasyprint import WeasyTemplateResponseMixin
from fuzzywuzzy import fuzz, process

# Squarelet
from squarelet.core.mixins import AdminLinkMixin
from squarelet.core.utils import (
    create_zendesk_ticket,
    format_stripe_error,
    get_redirect_url,
    get_stripe_dashboard_url,
)
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.denylist_domains import DENYLIST_DOMAINS
from squarelet.organizations.forms import (
    AddMemberForm,
    MergeForm,
    PaymentForm,
    UpdateForm,
)
from squarelet.organizations.mixins import (
    OrganizationAdminMixin,
    VerifiedJournalistMixin,
)
from squarelet.organizations.models import (
    Charge,
    Invitation,
    Membership,
    Organization,
    OrganizationEmailDomain,
)
from squarelet.organizations.tasks import (
    handle_charge_succeeded,
    handle_invoice_created,
    handle_invoice_failed,
    handle_invoice_finalized,
    handle_invoice_marked_uncollectible,
    handle_invoice_paid,
    handle_invoice_voided,
    sync_wix,
)

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
            ).get_pending_requests()
            if context["is_admin"]:
                context["invite_count"] = (
                    self.object.invitations.get_pending_requests().count()
                )

            context["can_auto_join"] = (
                self.request.user.can_auto_join(self.object)
                and not context["is_member"]
            )

        users = self.object.users.all()
        admins = users.filter(memberships__admin=True)
        if context.get("is_member"):
            context["users"] = users.order_by("-memberships__admin", "username")
        else:
            context["users"] = admins
        context["admins"] = admins

        return context

    def handle_join(self, request):
        self.organization = self.get_object()
        user = request.user

        # Already a member
        if self.organization.has_member(user):
            return

        # Auto join if allowed
        if user.can_auto_join(self.organization):
            self.organization.memberships.create(user=user)
            if self.organization.plan and self.organization.plan.wix:
                sync_wix.delay(
                    self.organization.pk,
                    self.organization.plan.pk,
                    user.pk,
                )
            messages.success(request, "You have successfully joined the organization!")
            return

        # For normal requests to join, check rate limit
        window_start = timezone.now() - timedelta(
            seconds=settings.ORG_JOIN_REQUEST_WINDOW
        )
        recent_requests = Invitation.objects.filter(
            user=user, request=True, created_at__gte=window_start
        ).count()

        if recent_requests >= settings.ORG_JOIN_REQUEST_LIMIT:
            messages.error(
                request,
                f"You have reached the limit of {settings.ORG_JOIN_REQUEST_LIMIT} "
                "join requests in the last "
                f"{settings.ORG_JOIN_REQUEST_WINDOW // 60} minutes. "
                "Please try again later.",
            )

            # Create ZenDesk ticket for review
            create_zendesk_ticket(
                subject="User reached join-request rate limit "
                f"({recent_requests} requests)",
                description=(
                    "The following user has reached the "
                    "rate-limit for joining organizations, "
                    f"sending {recent_requests} requests in the last "
                    f"{settings.ORG_JOIN_REQUEST_WINDOW} seconds:\n\n"
                    f"{settings.SQUARELET_URL}{user.get_absolute_url()}\n\n"
                    "This is a signal that the user may be "
                    "using their account in an inappropriate way."
                ),
                tags=["rate-limit", "join-request"],
            )
            return

        # Create join request, assuming they aren't rate limited
        invitation = self.organization.invitations.create(
            email=request.user.email, user=request.user, request=True
        )
        messages.success(
            request,
            _(
                "Request to join the organization sent!<br><br>"
                "We strongly recommend reaching out directly to one or all of "
                "the admins listed below to ensure your request is approved "
                "quickly. If all of the admins shown below have left the "
                "organization, please "
                '<a href="mailto:info@muckrock.com">contact support</a> '
                "for assistance.<br><br>"
            ),
        )
        invitation.send()

    def handle_leave(self, request):
        self.organization = self.get_object()
        is_member = self.organization.has_member(self.request.user)
        userid = request.POST.get("userid")
        if userid:
            if userid == str(request.user.id) and is_member:
                # Users removing themselves
                request.user.memberships.filter(organization=self.organization).delete()
                messages.success(request, _("You left the organization"))
            elif request.user.is_staff:
                # Staff removing another user
                user_model = get_user_model()
                try:
                    target_user = user_model.objects.get(pk=userid)
                    target_user.memberships.filter(
                        organization=self.organization
                    ).delete()
                    messages.success(
                        request,
                        _("%(username)s left the organization")
                        % {"username": target_user.username},
                    )
                except user_model.DoesNotExist:
                    messages.error(request, _("User not found"))
            else:
                # Only staff can remove other users
                messages.error(
                    request, _("You do not have permission to remove other users")
                )
        elif is_member:
            # User removing themselves (no userid provided)
            request.user.memberships.filter(organization=self.organization).delete()
            messages.success(request, _("You left the organization"))

    def handle_sync_wix(self, request):
        self.organization = self.get_object()
        if self.request.user.is_staff and self.organization.plan.wix:
            for wix_user in self.organization.users.all():
                sync_wix.delay(
                    self.organization.pk,
                    self.organization.plan.pk,
                    wix_user.pk,
                )
            messages.success(request, _("Wix sync started"))

    def post(self, request, *args, **kwargs):
        self.organization = self.get_object()

        if not self.request.user.is_authenticated:
            return redirect(self.organization)
        if request.POST.get("action") == "join":
            self.handle_join(request)
        elif request.POST.get("action") == "leave":
            self.handle_leave(request)
        elif request.POST.get("action") == "sync_wix":
            self.handle_sync_wix(request)
        return get_redirect_url(request, redirect(self.organization))


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if not user.is_authenticated:
            return context

        context["invitations"] = []
        context["potential_orgs"] = []
        if user.is_authenticated:
            context["pending_requests"] = list(user.get_pending_requests())
            context["pending_invitations"] = list(user.get_pending_invitations())
            context["potential_orgs"] = list(user.get_potential_organizations())

        context["has_pending"] = bool(
            context["pending_requests"]
            + context["pending_invitations"]
            + context["potential_orgs"]
        )
        context["has_verified_email"] = bool(user.get_verified_emails())
        context["admin_orgs"] = list(
            user.organizations.filter(individual=False, memberships__admin=True)
        )
        context["other_orgs"] = list(
            user.organizations.filter(
                individual=False, memberships__admin=False
            ).get_viewable(self.request.user)
        )
        context["potential_organizations"] = list(user.get_potential_organizations())
        context["pending_invitations"] = list(user.get_pending_invitations())

        return context


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
        new_plan = form.cleaned_data.get("plan")
        try:
            organization.set_subscription(
                token=form.cleaned_data["stripe_token"],
                plan=new_plan,
                max_users=form.cleaned_data.get("max_users"),
                user=self.request.user,
            )
        except stripe.error.StripeError as exc:
            user_message = format_stripe_error(exc)
            messages.error(self.request, f"Payment error: {user_message}")
        else:
            organization.set_receipt_emails(form.cleaned_data["receipt_emails"])
            if form.cleaned_data.get("remove_card_on_file"):
                organization.remove_card()
                messages.success(self.request, _("Credit card removed"))
            else:
                messages.success(
                    self.request,
                    (
                        _("Plan Updated")
                        if organization.individual
                        else _("Organization Updated")
                    ),
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


class ManageMembers(OrganizationAdminMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managemembers.html"

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        actions = {
            "addmember": self._handle_add_member,
            "addmember_link": self._handle_add_member_link,
            "revokeinvite": self._handle_revoke_invite,
            "resendinvite": self._handle_resend_invite,
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
            messages.error(
                request, addmember_form.errors.get("emails", ["Invalid input."])[0]
            )
        else:
            emails = addmember_form.cleaned_data["emails"]

            for email in emails:
                is_already_member = self.organization.has_member_by_email(email)
                existing_open_invite = self.organization.get_existing_open_invite(email)
                if is_already_member:
                    messages.info(
                        self.request,
                        f"{email} is already a member of this organization.",
                    )
                    continue

                if existing_open_invite:
                    existing_open_invite.send()
                    messages.success(
                        self.request,
                        f"Resent invitation to {email}.",
                    )
                    continue

                invitation = Invitation.objects.create(
                    organization=self.organization,
                    email=email,
                )
                invitation.send()

                messages.success(self.request, "Invitations sent")

        return redirect("organizations:manage-members", slug=self.organization.slug)

    def _handle_add_member_link(self, request):
        # Create an invitation and display it to the admin
        invitation = Invitation.objects.create(
            organization=self.organization,
        )
        url = reverse("organizations:invitation", args=(invitation.uuid,))
        messages.success(
            self.request,
            format_html(
                "Invitation link created:<p>{}{}</p>", settings.SQUARELET_URL, url
            ),
        )
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

    def _handle_resend_invite(self, request):
        return self._handle_invite(
            request,
            lambda invite: invite.send(),
            "Invitation resent successfully.",
        )

    def _handle_accept_invite(self, request):
        def accept_invite(invite):
            invite.accept()

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
        context["requested_invitations"] = (
            self.object.invitations.get_pending_requests()
        )
        context["pending_invitations"] = (
            self.object.invitations.get_pending_invitations()
        )
        return context


class InvitationAccept(DetailView):
    queryset = Invitation.objects.get_pending()
    slug_field = "uuid"
    slug_url_kwarg = "uuid"

    def dispatch(self, request, *args, **kwargs):
        """
        If the user is authenticated, associate the invitation with that user, so
        they can access it later.
        If not, store the invitation in the session, so that the invitation can be
        associated on login
        """
        if request.user.is_authenticated:
            Invitation.objects.filter(uuid=kwargs["uuid"]).update(user=request.user)
        else:
            request.session["invitation"] = str(kwargs["uuid"])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Accept the invitation"""
        if not request.user.is_authenticated:
            return HttpResponseBadRequest()
        invitation = self.get_object()
        action = request.POST.get("action")
        if action == "accept":
            invitation.accept(request.user)
            messages.success(request, "Invitation accepted")
            return get_redirect_url(request, redirect(invitation.organization))
        elif action == "reject":
            invitation.reject()
            if invitation.request:
                messages.info(request, "Invitation withdrawn")
            else:
                messages.info(request, "Invitation rejected")
            return get_redirect_url(request, redirect(request.user))
        else:
            messages.error(request, "Invalid choice")
            return get_redirect_url(request, redirect(request.user))


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


class PDFChargeDetail(WeasyTemplateResponseMixin, ChargeDetail):
    """Subclass to view receipt as PDF"""

    pdf_filename = "receipt.pdf"


@csrf_exempt
def stripe_webhook(request):  # pylint: disable=too-many-branches
    """Handle webhooks from stripe"""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        if settings.STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
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
    # https://docs.stripe.com/api/events/types

    # Log invoice-related webhooks with minimal noise
    if event_type.startswith("invoice."):
        invoice_id = event["data"]["object"].get("id")
        if invoice_id:
            stripe_link = get_stripe_dashboard_url("invoices", invoice_id)
            logger.info(
                "[STRIPE-WEBHOOK] %s: %s (%s)",
                event_type,
                invoice_id,
                stripe_link,
            )
        else:
            logger.info("[STRIPE-WEBHOOK] %s (no invoice ID)", event_type)
    else:
        # For non-invoice events, log with more detail
        success_msg = (
            "[STRIPE-WEBHOOK] Received Stripe webhook\n"
            "\tfrom:\t%(address)s\n"
            "\ttype:\t%(type)s\n"
            "\tdata:\t%(data)s\n"
        ) % {"address": request.META["REMOTE_ADDR"], "type": event_type, "data": event}
        logger.info(success_msg)
    if event_type == "charge.succeeded":
        handle_charge_succeeded.delay(event["data"]["object"])
    elif event_type == "invoice.payment_failed":
        handle_invoice_failed.delay(event["data"]["object"])
    elif event_type == "invoice.created":
        handle_invoice_created.delay(event["data"]["object"])
    elif event_type == "invoice.finalized":
        handle_invoice_finalized.delay(event["data"]["object"])
    elif event_type == "invoice.paid":
        # Listening for invoice.paid ensures we handle payments that
        # when happen when users pay them through Stripe or when staff
        # manually mark them as paid through the Stripe dashboard
        handle_invoice_paid.delay(event["data"]["object"])
    elif event_type == "invoice.marked_uncollectible":
        handle_invoice_marked_uncollectible.delay(event["data"]["object"])
    elif event_type == "invoice.voided":
        handle_invoice_voided.delay(event["data"]["object"])
    return HttpResponse()


class ManageDomains(VerifiedJournalistMixin, DetailView):
    queryset = Organization.objects.filter(individual=False)
    template_name = "organizations/organization_managedomains.html"

    def post(self, request, *args, **kwargs):
        """Handle form processing"""
        self.organization = self.get_object()

        actions = {
            "adddomain": self._handle_add_domain,
            "removedomain": self._handle_remove_domain,
        }
        action = request.POST.get("action")
        if action in actions:
            return actions[action](request)
        return self._bad_call(request)

    def _handle_add_domain(self, request):
        domain = request.POST.get("domain", "").strip().lower()

        # Validate domain format
        if not re.match(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$", domain):
            messages.error(
                request, "Invalid domain format. Please enter a valid domain."
            )
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Check for blacklisted domain
        if domain in DENYLIST_DOMAINS:
            messages.error(request, f"The domain {domain} is not allowed.")
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Prevent duplicates
        if OrganizationEmailDomain.objects.filter(
            organization=self.organization, domain=domain
        ).exists():
            messages.error(request, f"The domain {domain} is already added.")
            return redirect("organizations:manage-domains", slug=self.organization.slug)

        # Add the domain
        OrganizationEmailDomain.objects.create(
            organization=self.organization, domain=domain
        )
        messages.success(request, f"The domain {domain} was added successfully.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def _handle_remove_domain(self, request):
        domain = request.POST.get("domain", "").strip().lower()

        # Check if domain exists
        try:
            domain_entry = OrganizationEmailDomain.objects.get(
                organization=self.organization, domain=domain
            )

            # Only delete if domain exists
            domain_entry.delete()
            messages.success(request, f"The domain {domain} was removed successfully.")
        except OrganizationEmailDomain.DoesNotExist:
            # Provide a more detailed message in case the domain doesn't exist
            messages.error(
                request,
                f"The domain {domain} was not found or has already been removed.",
            )

        return redirect("organizations:manage-domains", slug=self.organization.slug)

    def get_context_data(self, **kwargs):
        self.organization = self.get_object()

        context = super().get_context_data(**kwargs)
        context["admin"] = self.request.user

        # Use 'domains' related_name for your OrganizationEmailDomain model
        context["domains"] = (
            self.organization.domains.all()
        )  # Corrected field to 'domains'
        return context

    def _bad_call(self, request):
        # Handle unexpected actions
        messages.error(request, "An unexpected error occurred.")
        return redirect("organizations:manage-domains", slug=self.organization.slug)


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
