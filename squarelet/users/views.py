# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http.response import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import (
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)

# Standard Library
import base64
import enum
import hashlib
import hmac
import json
import time

# Third Party
from allauth.account.utils import (
    get_next_redirect_url,
    has_verified_email,
    send_email_confirmation,
)
from allauth.account.views import LoginView as AllAuthLoginView
from allauth.mfa.adapter import get_adapter
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal.flows import activate_totp
from allauth.mfa.utils import is_mfa_enabled
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout

# Squarelet
from squarelet.core.forms import ImagePreviewWidget
from squarelet.core.layout import Field
from squarelet.core.mixins import AdminLinkMixin
from squarelet.organizations.models import ReceiptEmail
from squarelet.services.models import Service

# Local
from .models import User


# todo: move step definition to a more appropriate place
# todo: switch to StrEnum once we're on Python >=3.11
class OnboardingStep(enum.Enum):
    confirm_email = "Confirm email"
    join_org = "Join organizations"
    mfa = "Multi-factor authentication"


class UserDetailView(LoginRequiredMixin, AdminLinkMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def dispatch(self, request, *args, **kwargs):
        if kwargs["username"] != request.user.username and not request.user.is_staff:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.object
        context = super().get_context_data(**kwargs)
        context["other_orgs"] = (
            context["user"]
            .organizations.filter(individual=False)
            .get_viewable(self.request.user)
        )
        context["potential_organizations"] = user.get_potential_organizations()
        context["pending_invitations"] = user.get_pending_invitations()
        return context


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class UserUpdateView(LoginRequiredMixin, UpdateView):
    model = User

    def get_form_class(self):
        """Include username in form if the user hasn't changed their username yet"""
        fields = ["name", "avatar", "use_autologin"]
        if self.object.can_change_username:
            self.fields = ["username"] + fields
        else:
            self.fields = fields
        return super().get_form_class()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.helper = FormHelper()
        form.helper.layout = Layout(
            Fieldset("Name", Field("name")),
            (
                Fieldset("Username", Field("username"))
                if "username" in form.fields
                else None
            ),
            Fieldset("Avatar image", Field("avatar"), css_class="_cls-compactField"),
            Fieldset(
                "Autologin", Field("use_autologin"), css_class="_cls-compactField"
            ),
        )
        form.helper.form_tag = False
        form.fields["avatar"].widget = ImagePreviewWidget()
        return form

    def form_valid(self, form):
        self.object = form.save(commit=False)
        if self.request.user.username != self.object.username:
            self.object.can_change_username = False
        self.object.save()
        self.object.individual_organization.avatar = self.object.avatar
        self.object.individual_organization.name = self.object.username
        self.object.individual_organization.save()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        """The user object has the invalid data in it - refresh it from the database
        before displaying to the user
        """
        self.object.refresh_from_db()
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.object.username})

    def get_object(self, queryset=None):
        return User.objects.get(pk=self.request.user.pk)


class UserListView(LoginRequiredMixin, ListView):
    model = User


class UserOnboardingView(TemplateView):
    """Show onboarding steps for new or existing users after they log in"""

    template_name = "account/onboarding/base.html"  # Base template with includes

    def get_onboarding_step(self, request):
        """
        Check user account status and return the appropriate onboarding step
        Returns: (step_name, context_data)
        """
        user = request.user
        session = request.session
        # check_for = session.get("checkFor", [])

        # Initialize onboarding session if it doesn't exist
        if "onboarding" not in session:
            session["onboarding"] = {
                "email_check_completed": False,
                "mfa_step": "not_started",
            }
        # Onboarding progress state is tracked in the session
        onboarding = session["onboarding"]
        print(onboarding)
        if has_verified_email(user):
            onboarding["email_check_completed"] = True
            session.modified = True
        elif not onboarding["email_check_completed"]:
            return "confirm_email", {}

        # TODO: Verification check

        # Organization check
        has_orgs = user.organizations.filter(individual=False).exists()
        if not has_orgs:
            return OnboardingStep.join_org.name, {
                "invitations": user.get_pending_invitations(),
                "potential_orgs": user.get_potential_organizations().filter(
                    allow_auto_join=True
                ),
            }

        # MFA check
        # Check if this is user's first login
        is_first_login = (
            user.last_login is None or user.date_joined.date() == user.last_login.date()
        )
        mfa_step = onboarding.get("mfa_step", None)
        # Check for the "code_submitted" step first, since
        # is_mfa_enabled will be true when the step is active
        if mfa_step == "code_submitted":
            return "mfa_confirm", {}
        # Otherwise, if the user has MFA enabled, or if it's
        # not the right time to prompt, mark step as checked
        elif is_mfa_enabled(user) or is_first_login or not has_verified_email(user):
            onboarding["mfa_step"] = "completed"
            session.modified = True
        # Finally, if the user doesn't have MFA enabled,
        # ask if they want to opt-in, or show them setup
        elif mfa_step == "not_started":
            return "mfa_opt_in", {}
        elif mfa_step == "opted_in":
            return "mfa_setup", {}

        # If all checks pass, user has completed onboarding
        return None, {}

    def get_template_names(self):
        """Return the appropriate template based on onboarding step"""
        step, _ = self.get_onboarding_step(self.request)

        if step:
            return [f"account/onboarding/{step}.html"]

        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add the onboarding step to context
        step, step_context = self.get_onboarding_step(self.request)
        context["onboarding_step"] = step
        context.update(step_context)

        # Add the session params from login
        context["next_url"] = self.request.session.get("next_url", "/")
        context["intent"] = self.request.session.get("intent", None)
        context["service"] = Service.objects.filter(slug=context["intent"]).first()

        # For MFA setup, initialize the form and generate the SVG
        if step == "mfa_setup":
            activate_totp_form = ActivateTOTPForm(user=self.request.user)
            context["form"] = activate_totp_form
            adapter = get_adapter()
            totp_url = adapter.build_totp_url(
                self.request.user,
                context["form"].secret,
            )
            totp_svg = adapter.build_totp_svg(totp_url)
            base64_data = base64.b64encode(totp_svg.encode("utf8")).decode("utf-8")
            totp_data_uri = f"data:image/svg+xml;base64,{base64_data}"
            context.update(
                {
                    "totp_svg": totp_svg,
                    "totp_svg_data_uri": totp_data_uri,
                    "totp_url": totp_url,
                }
            )

        return context

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("account_login")

        # Check if onboarding is complete
        step, _ = self.get_onboarding_step(request)

        if step == "confirm_email":
            # If the user has not verified their email,
            # send a new confirmation message
            send_email_confirmation(request, request.user, False, request.user.email)

        if not step and "next_url" in request.session:
            # Onboarding complete, redirect to original destination
            next_url = request.session.pop("next_url")
            return redirect(next_url)

        if not step:
            return redirect("users:detail", username=request.user.username)

        # Otherwise, show the appropriate onboarding step
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("account_login")

        # Handle any form submissions for the current onboarding step
        step = request.POST.get("step")
        print(request.POST)
        if step == "confirm_email":
            # User has confirmed their email, mark as completed
            request.session["onboarding"]["email_check_completed"] = True
            request.session.modified = True
            print(
                "confirm email", request.session["onboarding"]["email_check_completed"]
            )

        elif step == "mfa_opt_in":
            choice = request.POST.get("enable_mfa")
            print(choice)
            if choice == "yes":
                # User opted-in for MFA, move to next step
                request.session["onboarding"]["mfa_step"] = "opted_in"
            else:
                # User skipped MFA, mark as completed
                messages.info(request, "Two-factor authentication skipped.")
                request.session["onboarding"]["mfa_step"] = "completed"
            request.session.modified = True

        elif step == "mfa_setup":
            # Check if the user skipped the MFA setup step
            if request.POST.get("mfa_setup") == "skip":
                request.session["onboarding"]["mfa_step"] = "completed"
                request.session.modified = True
                messages.info(request, "Two-factor authentication skipped.")
                return redirect("account_onboarding")
            # Process MFA setup - validate the code
            form = ActivateTOTPForm(user=request.user, data=request.POST)
            if form.is_valid():
                # Code validated successfully
                activate_totp(self.request, form)
                request.session["onboarding"]["mfa_step"] = "code_submitted"
                request.session.modified = True
                messages.success(request, "Two-factor authentication enabled.")
            else:
                # Rerender form with errors
                context = self.get_context_data(**kwargs)
                context["form"] = form
                messages.error(request, "Invalid verification code. Please try again.")
                return self.render_to_response(context)

        elif step == "mfa_confirm":
            # User has seen the confirmation screen, mark MFA as completed
            request.session["onboarding"]["mfa_step"] = "completed"
            request.session.modified = True

        # Redirect back to the same view to check the next step
        return redirect("account_onboarding")


class LoginView(AllAuthLoginView):
    def get(self, request, *args, **kwargs):
        """
        If the url_auth_token parameter is still present, it means the auth token failed
        to authenticate the user.  Redirect them to the nested next parameter instead of
        asking them to login
        """
        next_url = get_next_redirect_url(request)
        if "url_auth_token" in request.GET and next_url:
            return redirect(f"{settings.MUCKROCK_URL}{next_url}")
        return super().get(request, *args, **kwargs)


def mailgun_webhook(request):
    """Handle mailgun webhooks to keep track of user emails that have failed"""
    # pylint: disable=too-many-return-statements

    def verify(event):
        """Verify that the message is from mailgun"""
        token = event.get("token", "")
        timestamp = event.get("timestamp", "")
        signature = event.get("signature", "")
        hmac_digest = hmac.new(
            key=settings.MAILGUN_ACCESS_KEY.encode("utf8"),
            msg=f"{timestamp}{token}".encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        match = hmac.compare_digest(signature, str(hmac_digest))
        return match and int(timestamp) + 300 > time.time()

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("JSON decode error")

    if not verify(event.get("signature", {})):
        return HttpResponseForbidden()

    if "event-data" not in event:
        return HttpResponseBadRequest("Missing event-data")
    event = event["event-data"]

    if event.get("event") != "failed":
        return HttpResponse("OK")

    if "recipient" not in event:
        return HttpResponseBadRequest("Missing recipient")
    email = event["recipient"]

    User.objects.filter(email=email).update(email_failed=True)
    ReceiptEmail.objects.filter(email=email).update(failed=True)
    return HttpResponse("OK")


class Receipts(LoginRequiredMixin, TemplateView):
    """Subclass to view individual's receipts"""

    template_name = "organizations/organization_receipts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["organizations"] = self.request.user.organizations.filter(
            memberships__admin=True
        ).prefetch_related("charges")
        return context
