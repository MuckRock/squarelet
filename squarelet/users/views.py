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


class UserOnboardingView(TemplateView):
    """Show onboarding steps for new or existing users after they log in"""

    template_name = "account/onboarding/base.html"  # Base template with includes

    def get_onboarding_step(self, request):
        # pylint: disable=too-many-locals, too-many-return-statements
        """
        Check user account status and return the appropriate onboarding step
        Returns: (step_name, context_data)
        """
        user = request.user
        session = request.session
        # check_for = session.get("checkFor", [])

        # Initialize onboarding session if it doesn't exist
        if "onboarding" not in session:
            session["onboarding"] = {}

        for key, value in ONBOARDING_SESSION_DEFAULTS:
            session["onboarding"].setdefault(key, value)

        # Onboarding progress state is tracked in the session
        onboarding = session["onboarding"]
        if has_verified_email(user):
            onboarding["email_check_completed"] = True
            session.modified = True
        elif not onboarding["email_check_completed"]:
            return "confirm_email", {
                "email": user.email,
            }

        # TODO: Verification check

        # Organization check
        has_orgs = user.organizations.filter(individual=False).exists()
        invitations = list(user.get_pending_invitations())
        potential_orgs = list(
            user.get_potential_organizations().filter(allow_auto_join=True)
        )
        joinable_orgs_count = len(invitations + potential_orgs)
        if not has_orgs and not onboarding["join_org"] and joinable_orgs_count > 0:
            return "join_org", {
                "invitations": invitations,
                "potential_orgs": potential_orgs,
                "joinable_orgs_count": len(invitations + potential_orgs),
            }

        # Subscription check
        # If the user is signing up for a plan, the "plan" session variable
        # will be set to the plan slug. If not, it will be None.
        # We want to load both the individual and organization plans,
        # and then pass through the "active" plan based on the user's choice.
        # In order to enter the step, we need to check:
        # 1. if the plan is valid
        # 2. if the plan is professional, that the user is not already subscribed
        # 3. that the subscription step state is `not_started`
        plan = session.get("plan", None) or request.GET.get("plan", None)
        if (
            plan == "professional"
            and user.individual_organization.has_active_subscription()
            and onboarding["subscription"] == "not_started"
        ):
            # User is already subscribed to the professional plan
            onboarding["subscription"] = "completed"
            session["plan"] = None
            session.modified = True
        if plan and onboarding["subscription"] == "not_started":
            try:
                individual_plan = Plan.objects.get(slug="professional")
                group_plan = Plan.objects.get(slug="organization")
                selected_plan = Plan.objects.get(slug=plan)
                return "subscribe", {
                    "plans": {
                        "individual": individual_plan,
                        "group": group_plan,
                        "selected": selected_plan,
                    }
                }
            except Plan.DoesNotExist:
                print("Invalid plan slug:", plan)
        # MFA check
        # Check if this is user's first login
        is_first_login = request.session.get("first_login", False)
        is_snoozed = (
            user.last_mfa_prompt
            and timezone.now() - user.last_mfa_prompt
            < settings.MFA_PROMPT_SNOOZE_DURATION
        )
        # 2FA setup will fail if the user has any unverified emails,
        # even if they are not the primary email
        has_unverified_email = not has_verified_email(user) or (
            EmailAddress.objects.filter(user=user, verified=False).exists()
        )
        mfa_step = onboarding.get("mfa_step", None)
        # Check for the "code_submitted" step first, since
        # is_mfa_enabled will be true when the step is active
        if mfa_step == "code_submitted":
            return "mfa_confirm", {}
        # Otherwise, if the user has MFA enabled, or if it's
        # not the right time to prompt, mark step as checked
        elif (
            is_mfa_enabled(user) or is_first_login or is_snoozed or has_unverified_email
        ):
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

        # For Subscription, initialize the form and get the user's organizations
        if step == "subscribe":
            plans = step_context.get("plans")
            if plans:
                individual_form = PremiumSubscriptionForm(
                    plan=plans["individual"], user=self.request.user
                )
                group_form = PremiumSubscriptionForm(
                    plan=plans["group"], user=self.request.user
                )
            context.update(
                {
                    "forms": {
                        "individual": individual_form,
                        "group": group_form,
                    },
                    "individual_org": self.request.user.individual_organization,
                    "group_orgs": (
                        self.request.user.organizations.filter(
                            individual=False,
                            memberships__user=self.request.user,
                            memberships__admin=True,
                        ).order_by("name")
                    ),
                }
            )

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

    # TODO: Refactor the UserOnboardingView to reduce branches and statements,
    # perhaps using a dictionary to map steps to their respective handlers.
    # pylint: disable=too-many-branches, too-many-statements
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("account_login")

        # Handle any form submissions for the current onboarding step
        step = request.POST.get("step")
        if step == "confirm_email":
            # User has confirmed their email, mark as completed
            request.session["onboarding"]["email_check_completed"] = True
            request.session.modified = True

        elif step == "mfa_opt_in":
            choice = request.POST.get("enable_mfa")
            if choice == "yes":
                # User opted-in for MFA, move to next step
                request.session["onboarding"]["mfa_step"] = "opted_in"
            else:
                # User skipped MFA, mark as completed
                messages.info(request, "Two-factor authentication skipped.")
                request.session["onboarding"]["mfa_step"] = "completed"

                # Update last_mfa_prompt to now
                request.user.last_mfa_prompt = timezone.now()
                request.user.save(update_fields=["last_mfa_prompt"])
            request.session.modified = True

        elif step == "mfa_setup":
            # Check if the user skipped the MFA setup step
            if request.POST.get("mfa_setup") == "skip":
                # User skipped MFA, mark as completed
                request.session["onboarding"]["mfa_step"] = "completed"
                request.session.modified = True
                # Update last_mfa_prompt to now
                request.user.last_mfa_prompt = timezone.now()
                request.user.save(update_fields=["last_mfa_prompt"])
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

        elif step == "subscribe":
            # Handle subscription form submission
            # the form will have the plan, the organization, and the Stripe token
            # ---
            # First, check if the user skipped this step
            if request.POST.get("submit-type") == "skip":
                request.session["onboarding"]["subscription"] = "completed"
                request.session.modified = True
                messages.info(request, "Subscription skipped.")
                return redirect("account_onboarding")
            # Otherwise, initialize the form with the submitted data,
            # validate it, and save it if valid. If invalid, rerender
            # the page with the form errors.
            plan_id = request.POST.get("plan")
            org_id = request.POST.get("organization")
            plan = Plan.objects.get(pk=plan_id)
            form = PremiumSubscriptionForm(request.POST, plan=plan, user=request.user)
            if form.is_valid() and form.save(request.user):
                # Create a subscription for the selected organization
                messages.success(request, "Subscription created successfully.")
                request.session["onboarding"]["subscription"] = "completed"
                request.session.modified = True
            else:
                context = self.get_context_data(**kwargs)
                if org_id == request.user.individual_organization.pk:
                    context["forms"]["individual"] = form
                else:
                    context["forms"]["group"] = form
                messages.error(
                    request, "Error creating subscription. Please try again."
                )
                return self.render_to_response(context)

        elif step == "join_org" and request.POST.get("join_org") == "skip":
            request.session["onboarding"]["join_org"] = True
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
