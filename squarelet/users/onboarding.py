# Django
from django.conf import settings
from django.contrib import messages
from django.utils import timezone

# Standard Library
import base64
import logging
import sys

# Third Party
from allauth.account.models import EmailAddress
from allauth.account.utils import has_verified_email
from allauth.mfa.adapter import get_adapter
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal.flows import activate_totp

# Squarelet
from squarelet.organizations.models.payment import Plan
from squarelet.users.forms import PremiumSubscriptionForm

logger = logging.getLogger(__name__)


def onboarding_check(request):
    """
    Checks for onboarding-related GET parameters and stores them in session.
    The value of the "check" parameter should correspond to a step name.
    """
    request.session["onboarding_check"] = request.GET.getlist("check")
    request.session.modified = True


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


class VerificationStep(OnboardingStep):
    """Prompt users to apply for newsroom verification"""

    name = "verification"
    template_name = "account/onboarding/verification.html"

    def should_execute(self, request):
        """As a new user, I’ll enter the verification onboarding flow if I'm
        neither individually verified nor a member of a verified organization,
        and I'm taking an action that requires verification."""
        user = request.user
        done = self.name in request.session.get("onboarding", {})
        check = self.name in request.session.get("onboarding_check", [])
        individually_verified = user.individual_organization.verified_journalist
        org_verified = user.organizations.filter(
            individual=False,
            memberships__user=user,
            verified_journalist=True,
        ).exists()
        # if we are checking, we only show if the user is not verified
        return not done and check and (not individually_verified or not org_verified)

    def get_context_data(self, request):
        """Return unverified organizations and individual verification status"""
        user = request.user
        unverified_orgs = user.organizations.filter(
            individual=False,
            memberships__user=user,
            verified_journalist=False,
        ).order_by("name")
        individually_verified = user.individual_organization.verified_journalist
        return {
            "unverified_orgs": unverified_orgs,
            "individually_verified": individually_verified,
        }

    def handle_post(self, request):
        if request.POST.get("step") != self.name:
            return False

        # Handle skip action
        if request.POST.get("verification") == "skip":
            request.session["onboarding"]["verification"] = True
            request.session.modified = True
            return True

        return None


class OrganizationJoinStep(OnboardingStep):
    """Prompt users to join an organization"""

    name = "join_org"

    def _get_joinable_orgs(self, user):
        """Get organizations the user can join"""
        invitations = list(user.get_pending_invitations())
        potential_orgs = list(user.get_potential_organizations())
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
            logger.error(
                "[ONBOARDING] Invalid plan slug: %s", plan_slug, exc_info=sys.exc_info()
            )
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
        error_form_plan = getattr(request, "_subscription_form_plan", None)
        if error_form and error_form_plan:
            if error_form_plan.pk == plans["individual"].pk:
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
            setattr(request, "_subscription_form_plan", plan)
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
        if user.has_mfa_enabled:
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
            # Check if there's a TOTP secret in the session
            secret = request.session.get("totp_secret", None)
            if secret:
                # If we have a secret, use it to initialize the form
                form = ActivateTOTPForm(user=request.user)
                form.secret = secret
            else:
                # Store the form secret in the session
                form = ActivateTOTPForm(user=request.user)
                request.session["totp_secret"] = form.secret
                request.session.modified = True

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
            # Clear the secret from session when skipping
            request.session.pop("totp_secret", None)
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
        if "totp_secret" in request.session:
            # If we have a secret in the session, set it on the form
            form.secret = request.session["totp_secret"]

        if form.is_valid():
            # Code validated successfully
            activate_totp(request, form)
            # Clear the TOTP secret from the session
            request.session.pop("totp_secret", None)
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
            VerificationStep(),
            MFAOptInStep(),
            MFASetupStep(),
            MFAConfirmStep(),
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
