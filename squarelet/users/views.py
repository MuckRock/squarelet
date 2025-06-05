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
from django.utils import timezone
from django.views.generic import (
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)

# Standard Library
import base64
import hashlib
import hmac
import json
import time

# Third Party
from allauth.account.models import EmailAddress
from allauth.account.utils import (
    get_next_redirect_url,
    has_verified_email,
    send_email_confirmation,
)
from allauth.account.views import (
    LoginView as AllAuthLoginView,
    SignupView as AllAuthSignupView,
)
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
from squarelet.organizations.models.payment import Plan
from squarelet.services.models import Service
from squarelet.users.forms import PremiumSubscriptionForm, SignupForm

# Local
from .models import User

ONBOARDING_SESSION_DEFAULTS = (
    ("email_check_completed", False),
    ("mfa_step", "not_started"),
    ("join_org", False),
    ("subscription", "not_started"),
)


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


class OnboardingStep:
    """Base class for onboarding steps"""

    name = None
    template_name = None

    def should_execute(self, request):
        """Check if this step should be executed"""
        raise NotImplementedError

    def get_context_data(self, request):
        """Return context data for the step"""
        return {}

    def handle_post(self, request):
        """Handle POST requests for the step"""
        return None

    def get_template_name(self):
        """Return the template name for the step"""
        if self.template_name:
            return self.template_name
        return f"account/onboarding/{self.name}.html"


class EmailConfirmationStep(OnboardingStep):
    """Step for confirming the user's email address"""

    name = "confirm_email"

    def should_execute(self, request):
        """Show this step if the user has not confirmed their email"""
        user = request.user
        session = request.session
        onboarding = session.get("onboarding", {})

        if has_verified_email(user):
            onboarding["email_check_completed"] = True
            session.modified = True
            return False

        return not onboarding.get("email_check_completed", False)

    def get_context_data(self, request):
        return {"email": request.user.email}

    def handle_post(self, request):
        """Mark email confirmation as completed"""
        if request.POST.get("step") == self.name:
            request.session["onboarding"]["email_check_completed"] = True
            request.session.modified = True
        return True


class OrganizationJoinStep(OnboardingStep):
    """Prompt users to join an organization"""

    name = "join_org"

    def _get_joinable_orgs(self, user):
        """Get organizations the user can join"""
        invitations = list(user.get_pending_invitations())
        potential_orgs = list(
            user.get_potential_organizations().filter(allow_auto_join=True)
        )
        return invitations, potential_orgs

    def should_execute(self, request):
        """Show if user has no organizations and can join one"""
        user = request.user
        session = request.session
        onboarding = session.get("onboarding", {})

        has_orgs = user.organizations.filter(individual=False).exists()
        if has_orgs or onboarding.get("join_org", False):
            return False

        invitations, potential_orgs = self._get_joinable_orgs(user)
        return len(invitations + potential_orgs) > 0

    def get_context_data(self, request):
        user = request.user
        invitations, potential_orgs = self._get_joinable_orgs(user)
        return {
            "invitations": invitations,
            "potential_orgs": potential_orgs,
            "joinable_orgs_count": len(invitations + potential_orgs),
        }

    def handle_post(self, request):
        """Handle organization joining form submission"""
        if request.POST.get("step") != self.name:
            return None

        # Handle skip action
        if request.POST.get("join_org") == "skip":
            request.session["onboarding"]["join_org"] = True
            request.session.modified = True
            return True

        # TODO: Add handling for actual organization joining
        # This would involve processing invitation acceptances or
        # automatic organization joining based on the form data

        return None


class SubscriptionStep(OnboardingStep):
    """Handle subscription onboarding step"""

    # If the user is signing up for a plan, the "plan" session variable
    # will be set to the plan slug. If not, it will be None.
    # We want to load both the individual and organization plans,
    # and then pass through the "active" plan based on the user's choice.
    # In order to enter the step, we need to check:
    # 1. if the plan is valid
    # 2. if the plan is professional, that the user is not already subscribed
    # 3. that the subscription step state is `not_started`

    name = "subscribe"

    def _get_subscription_plans(self, request):
        """Get subscription data for the step"""
        session = request.session
        plan_slug = session.get("plan", None) or request.GET.get("plan", None)

        plans = {
            "individual": None,
            "group": None,
            "selected": None,
        }

        if not plan_slug:
            return plans

        try:
            plans["individual"] = Plan.objects.get(slug="professional")
            plans["group"] = Plan.objects.get(slug="organization")
            plans["selected"] = Plan.objects.get(slug=plan_slug)
            return plans
        except Plan.DoesNotExist:
            print("Invalid plan slug:", plan_slug)
            return plans

    def should_execute(self, request):
        """Show this step if the user has no active subscription"""
        user = request.user
        session = request.session
        onboarding = session.get("onboarding", {})

        # The state of the step should be "not_started"
        if onboarding.get("subscription") != "not_started":
            return False
        # The plans should all exist
        plans = self._get_subscription_plans(request)
        found_plans = all(plans.values())
        if not found_plans:
            return False
        # If the selected plan is "professional",
        # check if the user has an active subscription
        if (
            plans["selected"].slug == "professional"
            and user.individual_organization.has_active_subscription()
        ):
            onboarding["subscription"] = "completed"
            session["plan"] = None
            session.modified = True
            return False
        # We have ruled out the negative cases,
        # so we can show the subscription step
        return True

    def get_context_data(self, request):
        """Return context data for the subscription step"""
        user = request.user
        plans = self._get_subscription_plans(request)
        if not all(plans.values()):
            return {}

        # Check for a form with errors from a failed POST
        error_form = getattr(request, "_subscription_form_errors", None)
        if error_form:
            if error_form.plan == plans["individual"]:
                individual_form = error_form
                group_form = PremiumSubscriptionForm(
                    plan=plans["group"], user=request.user
                )
            else:
                individual_form = PremiumSubscriptionForm(
                    plan=plans["individual"], user=request.user
                )
                group_form = error_form
        else:
            # Create fresh forms
            individual_form = PremiumSubscriptionForm(
                plan=plans["individual"], user=request.user
            )
            group_form = PremiumSubscriptionForm(plan=plans["group"], user=request.user)

        # Get organizations for the user
        individual_org = user.individual_organization
        group_orgs = user.organizations.filter(
            individual=False,
            memberships__user=user,
            memberships__admin=True,
        ).order_by("name")

        return {
            "plans": plans,
            "forms": {
                "individual": individual_form,
                "group": group_form,
            },
            "individual_org": individual_org,
            "group_orgs": group_orgs,
        }

    def handle_post(self, request):
        """Handle subscription form submission"""
        # The form will have the plan, the organization, and the Stripe token
        # First, check for a step mismatch:
        if request.POST.get("step") != self.name:
            return False

        # Then, check if the user skipped this step:
        if request.POST.get("submit-type") == "skip":
            request.session["onboarding"]["subscription"] = "completed"
            request.session.modified = True
            messages.info(request, "Subscription skipped.")
            return True

        # Finally, initialize the form with the submitted data, validate it, and
        # save it if valid. If invalid, rerender the page with the form errors.
        plan_id = request.POST.get("plan")

        try:
            plan_id = int(plan_id)
            plan = Plan.objects.get(pk=plan_id)
        except (ValueError, TypeError, Plan.DoesNotExist):
            messages.error(request, "Invalid plan selected.")
            return False  # Let the view re-render with the error

        form = PremiumSubscriptionForm(request.POST, plan=plan, user=request.user)
        if form.is_valid() and form.save(request.user):
            # Create a subscription for the selected organization
            messages.success(request, "Subscription created successfully.")
            request.session["onboarding"]["subscription"] = "completed"
            request.session.modified = True
            return True
        else:
            # Store the form with errors for re-rendering
            setattr(request, "_subscription_form_errors", form)
            messages.error(request, "Error creating subscription. Please try again.")
            return False


class MFAOptInStep(OnboardingStep):
    """Step for opting into MFA"""

    name = "mfa_opt_in"

    def should_execute(self, request):
        """Show this step if the user has not opted into MFA"""
        user = request.user
        session = request.session
        onboarding = session.get("onboarding", {})
        mfa_step = onboarding.get("mfa_step", "not_started")

        # If the user has already opted in or completed MFA, skip this step
        if mfa_step != "not_started":
            return False

        # If the user has MFA enabled, skip this step
        if is_mfa_enabled(user):
            onboarding["mfa_step"] = "completed"
            session.modified = True
            return False

        # Skip if not the right time to prompt
        is_first_login = request.session.get("first_login", False)
        is_snoozed = (
            user.last_mfa_prompt
            and timezone.now() - user.last_mfa_prompt
            < settings.MFA_PROMPT_SNOOZE_DURATION
        )
        # 2FA setup will fail if the user has any unverified emails,
        # even if they are not the primary email
        has_any_unverified_email = not has_verified_email(user) or (
            EmailAddress.objects.filter(user=user, verified=False).exists()
        )

        if is_first_login or is_snoozed or has_any_unverified_email:
            onboarding["mfa_step"] = "completed"
            session.modified = True
            return False

        return True

    def handle_post(self, request):
        """Handle the user's choice to enable or skip MFA"""
        if request.POST.get("step") != self.name:
            return False
        choice = request.POST.get("enable_mfa")
        if choice == "yes":
            # User opted-in for MFA, move to next step
            request.session["onboarding"]["mfa_step"] = "opted_in"
            request.session.modified = True
            return True
        else:
            # User skipped MFA, mark as completed
            messages.info(request, "Two-factor authentication skipped.")
            request.session["onboarding"]["mfa_step"] = "completed"
            request.session.modified = True

            # Update last_mfa_prompt to now
            request.user.last_mfa_prompt = timezone.now()
            request.user.save(update_fields=["last_mfa_prompt"])
            return True


class MFASetupStep(OnboardingStep):
    """Show QR code and collect TOTP code"""

    name = "mfa_setup"

    def should_execute(self, request):
        """Show MFA setup if user has opted in"""
        session = request.session
        onboarding = session.get("onboarding", {})
        mfa_step = onboarding.get("mfa_step", "not_started")
        return mfa_step == "opted_in"

    def get_context_data(self, request):
        """Return MFA setup form and QR code"""
        # First check if we have a form with errors from a previous POST
        error_form = getattr(request, "_mfa_setup_form_errors", None)
        if error_form:
            # If we have an error form, use it
            form = error_form
        else:
            # Otherwise, create a new form
            form = ActivateTOTPForm(user=request.user)

        # Generate the TOTP URL and SVG
        adapter = get_adapter()
        totp_url = adapter.build_totp_url(request.user, form.secret)
        totp_svg = adapter.build_totp_svg(totp_url)
        base64_data = base64.b64encode(totp_svg.encode("utf8")).decode("utf-8")
        totp_data_uri = f"data:image/svg+xml;base64,{base64_data}"

        return {
            "form": form,
            "totp_svg": totp_svg,
            "totp_svg_data_uri": totp_data_uri,
            "totp_url": totp_url,
        }

    def handle_post(self, request):
        """Handle MFA setup form submission"""
        if request.POST.get("step") != self.name:
            return None

        # Check if the user skipped the MFA setup step
        if request.POST.get("mfa_setup") == "skip":
            # User skipped MFA, mark as completed
            request.session["onboarding"]["mfa_step"] = "completed"
            request.session.modified = True
            # Update last_mfa_prompt to now
            request.user.last_mfa_prompt = timezone.now()
            request.user.save(update_fields=["last_mfa_prompt"])
            messages.info(request, "Two-factor authentication skipped.")
            return True
        # Process MFA setup - validate the code
        form = ActivateTOTPForm(user=request.user, data=request.POST)
        if form.is_valid():
            # Code validated successfully
            activate_totp(request, form)
            request.session["onboarding"]["mfa_step"] = "code_submitted"
            request.session.modified = True
            messages.success(request, "Two-factor authentication enabled.")
            return True
        else:
            # Rerender form with errors
            setattr(request, "_mfa_setup_form_errors", form)
            messages.error(request, "Invalid verification code. Please try again.")
            return False


class MFAConfirmStep(OnboardingStep):
    """Confirmation step after MFA setup"""

    name = "mfa_confirm"

    def should_execute(self, request):
        """Show this step if the user has submitted the MFA code"""
        session = request.session
        onboarding = session.get("onboarding", {})
        mfa_step = onboarding.get("mfa_step", "not_started")
        return mfa_step == "code_submitted"

    def handle_post(self, request):
        """Mark MFA as completed"""
        if request.POST.get("step") == self.name:
            # User has seen the confirmation screen, mark MFA as completed
            request.session["onboarding"]["mfa_step"] = "completed"
            request.session.modified = True
            return True
        return None


class OnboardingStepRegistry:
    """Registry for managing onboarding steps"""

    def __init__(self):
        self.steps = [
            EmailConfirmationStep(),
            OrganizationJoinStep(),
            SubscriptionStep(),
            MFAOptInStep(),
            MFASetupStep(),
            MFAConfirmStep(),
            # More steps will be added here as we migrate them
            # TODO: Verification check
        ]

    def get_current_step(self, request):
        """Find the first step that should be executed"""
        for step in self.steps:
            if step.should_execute(request):
                return step.name, step.get_context_data(request)
        return None, {}

    def get_step_by_name(self, name):
        """Get a specific step by name"""
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def handle_post(self, request, step_name):
        """Handle POST request for a specific step"""
        step = self.get_step_by_name(step_name)
        if step:
            return step.handle_post(request)
        return None

    def get_template_names(self, request, step_name):
        """Get the template names for a specific step"""
        step = self.get_step_by_name(step_name)
        if step:
            return [step.get_template_name()]
        return []


class UserOnboardingView(TemplateView):
    """Show onboarding steps for new or existing users after they log in"""

    template_name = "account/onboarding/base.html"  # Base template with includes

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.step_registry = OnboardingStepRegistry()

    def _initialize_onboarding_session(self, request):
        """Initialize the onboarding session with default values"""
        session = request.session
        if "onboarding" not in session or not isinstance(session["onboarding"], dict):
            session["onboarding"] = {}
        for key, value in ONBOARDING_SESSION_DEFAULTS:
            session["onboarding"].setdefault(key, value)

    def get_onboarding_step(self, request):
        """
        Check user account status and return the appropriate onboarding step
        Returns: (step_name, context_data)
        """
        self._initialize_onboarding_session(request)

        # Check registry steps
        # check_for = session.get("checkFor", [])
        step_name, context = self.step_registry.get_current_step(request)
        if step_name:
            # If a step is found, return it immediately
            return step_name, context

        # If all checks pass, user has completed onboarding
        return None, {}

    def get_template_names(self):
        """Return the appropriate template based on onboarding step"""
        step, _ = self.get_onboarding_step(self.request)

        if step:
            return self.step_registry.get_template_names(self.request, step)

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

        return context

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("account_login")

        # Check if onboarding is complete
        step, _ = self.get_onboarding_step(request)

        is_first_login = request.session.get("first_login", False)
        if step == "confirm_email" and not is_first_login:
            # If the user just signed up, they are already sent the confirmation.
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

        self._initialize_onboarding_session(request)

        # Handle any form submissions for the current onboarding step
        step = request.POST.get("step")
        current_step_name, _ = self.get_onboarding_step(request)

        # Try registry steps first
        success = self.step_registry.handle_post(request, step)
        if success is False and step == current_step_name:
            # If registry step returned False, it means there was a validation error
            # and we need to re-render the current step with errors
            context = self.get_context_data(**kwargs)
            return self.render_to_response(context)

        # Otherwise, reload the pipeline to get the next step
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


class SignupView(AllAuthSignupView):
    """Pass the request to the form"""

    form_class = SignupForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


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
