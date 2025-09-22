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
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)

# Standard Library
import hashlib
import hmac
import json
import logging
import sys
import time
from datetime import datetime

# Third Party
from allauth.account.utils import get_next_redirect_url, send_email_confirmation
from allauth.account.views import (
    EmailView as AllAuthEmailView,
    LoginView as AllAuthLoginView,
    SignupView as AllAuthSignupView,
)
from allauth.mfa import app_settings
from allauth.mfa.models import Authenticator
from allauth.mfa.utils import is_mfa_enabled
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.internal import flows
from allauth.socialaccount.views import ConnectionsView

# Squarelet
from squarelet.core.mixins import AdminLinkMixin
from squarelet.organizations.models import ReceiptEmail
from squarelet.organizations.models.payment import Plan
from squarelet.organizations.views import UpdateSubscription
from squarelet.services.models import Service
from squarelet.users.forms import (
    SignupForm,
    UserAutologinPreferenceForm,
    UserUpdateForm,
)
from squarelet.users.onboarding import OnboardingStepRegistry, onboarding_check

# Local
from .models import User

logger = logging.getLogger(__name__)

ONBOARDING_SESSION_DEFAULTS = (
    ("email_check_completed", False),
    ("mfa_step", "not_started"),
    ("join_org", False),
    ("subscription", "not_started"),
)


class UserRedirectView(LoginRequiredMixin, RedirectView):
    """Redirects legacy user routes to username-based routes for the current user"""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        target_view = kwargs.get("target_view")
        return reverse(
            f"users:{target_view}", kwargs={"username": self.request.user.username}
        )


class StaffAccessMixin:
    """Mixin to provide staff access control for user views"""

    def dispatch(self, request, *args, **kwargs):
        username = kwargs.get("username")
        if username != request.user.username and not request.user.is_staff:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class UserEmailView(AllAuthEmailView):
    """Custom email view to redirect user after email operations."""

    def get_success_url(self):
        """Redirect to the previous page after a successful email operation."""
        return self.request.META.get("HTTP_REFERER") or reverse(
            "users:detail", kwargs={"username": self.request.user.username}
        )


class UserConnectionsView(ConnectionsView):
    """
    Override the connections view to redirect
    to user detail page after operations.
    """

    def get_success_url(self):
        """Redirect to the user detail page after a successful connection operation."""
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class UserListView(LoginRequiredMixin, ListView):
    model = User


class UserDetailView(LoginRequiredMixin, StaffAccessMixin, AdminLinkMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_context_data(self, **kwargs):
        user = self.object
        context = super().get_context_data(**kwargs)
        context["admin_orgs"] = list(
            user.organizations.filter(individual=False, memberships__admin=True)
        )
        context["other_orgs"] = list(
            user.organizations.filter(
                individual=False, memberships__admin=False
            ).get_viewable(self.request.user)
        )
        context["is_own_page"] = user == self.request.user
        context["potential_organizations"] = list(user.get_potential_organizations())
        context["pending_invitations"] = list(user.get_pending_invitations())
        context["pending_requests"] = list(user.get_pending_requests())
        context["verified"] = user.verified_journalist()
        context["verified_organizations"] = list(
            user.organizations.filter(verified_journalist=True, individual=False)
        )
        context["individually_verified"] = (
            user.individual_organization.verified_journalist
        )
        context["emails"] = user.emailaddress_set.all()
        context["has_unverified_emails"] = user.emailaddress_set.filter(
            verified=False
        ).exists()
        context["is_mfa_enabled"] = is_mfa_enabled(user)
        context["RECOVERY_CODE_COUNT"] = app_settings.RECOVERY_CODE_COUNT
        context["unused_code_count"] = len(self.get_recovery_codes())
        # Get the current plan and subscription, if any
        individual_org = user.individual_organization
        current_plan = None
        upgrade_plan = Plan.objects.get(slug="professional")
        subscription = None
        if hasattr(individual_org, "subscriptions"):
            subscription = individual_org.subscriptions.first()
            if subscription and hasattr(subscription, "plan"):
                current_plan = subscription.plan
                upgrade_plan = None
        context["current_plan"] = current_plan
        context["upgrade_plan"] = upgrade_plan
        # Get card, next charge date, and cancelled status for active subscription
        if current_plan and subscription:
            customer = getattr(individual_org, "customer", None)
            if callable(customer):
                customer = customer()
            context["current_plan_card"] = getattr(customer, "card", None)
            # Stripe subscription may have next charge date
            stripe_sub = getattr(subscription, "stripe_subscription", None)
            if stripe_sub:
                # Try to get next charge date from Stripe subscription
                time_stamp = getattr(stripe_sub, "current_period_end", None)
                if time_stamp:
                    tz_datetime = datetime.fromtimestamp(
                        time_stamp, tz=timezone.get_current_timezone()
                    )
                    context["current_plan_next_charge_date"] = tz_datetime.date()
            # Check if the plan is cancelled
            context["current_plan_cancelled"] = getattr(subscription, "cancelled", None)
        # Autologin preference form
        context["autologin_form"] = UserAutologinPreferenceForm(instance=user)
        return context

    def get_recovery_codes(self):
        "Get unused recovery codes"
        authenticator = Authenticator.objects.filter(
            user=self.request.user,
            type=Authenticator.Type.RECOVERY_CODES,
        ).first()

        if not authenticator:
            return []

        return authenticator.wrap().get_unused_codes()

    def post(self, request, *args, **kwargs):
        """Handle updates to simple user settings (currently autologin toggle)."""
        self.object = self.get_object()
        form = UserAutologinPreferenceForm(request.POST, instance=self.object)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Your automatic login preference has been updated."),
            )
        else:
            messages.error(
                request,
                _(
                    "We couldn't update your automatic login preference. "
                    "Please try again."
                ),
            )
        return HttpResponseRedirect(
            reverse("users:detail", kwargs={"username": self.object.username})
        )


class UserUpdateView(LoginRequiredMixin, StaffAccessMixin, AdminLinkMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        self.object = form.save(commit=False)

        # Get the original username from database to compare with the new one
        original_user = User.objects.get(pk=self.object.pk)
        username_changed = original_user.username != self.object.username
        if username_changed:
            self.object.can_change_username = False

        self.object.save()
        # TODO: We probably don't need to be keeping the avatar in sync
        # across both the user and their individual organization.
        # Long term, it might be simpler to maintain profile information
        # in the individual org, and remove personalization fields
        # from the user model. User should really be an auth-oriented model.
        self.object.individual_organization.avatar = self.object.avatar
        self.object.individual_organization.name = self.object.username
        self.object.individual_organization.save()
        messages.success(
            self.request,
            _("Your profile changes have been saved."),
        )
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        """The user object has the invalid data in it - refresh it from the database
        before displaying to the user
        """
        messages.error(
            self.request,
            _("There were errors saving your profile. Please review the form below."),
        )
        self.object.refresh_from_db()
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.object.username})


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

        if not step:
            # Onboarding is complete, clear the session store
            request.session.pop("onboarding_check", None)
            request.session.modified = True

        if not step and "next_url" in request.session:
            # Onboarding complete, redirect to original destination
            next_url = request.session.pop("next_url")
            return redirect(next_url)

        if not step:
            return redirect("users:detail", username=request.user.username)

        # Otherwise, show the appropriate onboarding step
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Handle POST requests for onboarding steps"""
        if not request.user.is_authenticated:
            return redirect("account_login")

        self._initialize_onboarding_session(request)

        step = request.POST.get("step")
        current_step_name, _ = self.get_onboarding_step(request)
        # Make sure the form data matches the session state
        if step and step == current_step_name:
            # If registry step returns False, it means there was a validation
            # error and we need to re-render the current step with errors
            success = self.step_registry.handle_post(request, step)
            if success is False:
                context = self.get_context_data(**kwargs)
                return self.render_to_response(context)
        else:
            logger.error(
                "[ONBOARDING] Onboarding step mismatch", exc_info=sys.exc_info()
            )

        # Otherwise, reload the pipeline to get the next step
        return redirect("account_onboarding")


class LoginView(AllAuthLoginView):
    def get(self, request, *args, **kwargs):
        """
        If the url_auth_token parameter is still present, it means the auth token failed
        to authenticate the user.  Redirect them to the nested next parameter instead of
        asking them to login
        """
        onboarding_check(request)
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

    def get(self, request, *args, **kwargs):
        onboarding_check(request)
        if self.request.session.get("socialaccount_sociallogin_clear"):
            flows.signup.clear_pending_signup(self.request)
            self.request.session.pop("socialaccount_sociallogin_clear")
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        sociallogin = flows.signup.get_pending_signup(self.request)
        if sociallogin:
            # pre-fill the form with the data the social provider returns
            initial = get_social_adapter().get_signup_form_initial_data(sociallogin)
            self.request.session["socialaccount_sociallogin_clear"] = True
        return initial

    def form_valid(self, form):
        sociallogin = flows.signup.get_pending_signup(self.request)
        if sociallogin:
            flows.signup.clear_pending_signup(self.request)
            # do not setup email here, as it will be set up when completing
            # the social signup flow
            user = form.save(self.request, setup_email=False)
            sociallogin.user = user
            sociallogin.save(self.request)
            return flows.signup.complete_social_signup(self.request, sociallogin)
        else:
            return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # if this is an attempted social login, make them confirm if they
        # want to create a new account or log in to an existing one
        sociallogin = flows.signup.get_pending_signup(self.request)
        confirm_sociallogin = self.request.GET.get("confirm")
        context["confirm_sociallogin"] = sociallogin and not confirm_sociallogin
        if sociallogin and not confirm_sociallogin:
            context["sociallogin_email"] = sociallogin.user.email
        return context


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


class Receipts(LoginRequiredMixin, StaffAccessMixin, TemplateView):
    """Subclass to view individual's receipts"""

    template_name = "organizations/organization_receipts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        username = kwargs.get("username")
        target_user = User.objects.get(username=username)
        context["organizations"] = target_user.organizations.filter(
            memberships__admin=True
        ).prefetch_related("charges")
        return context


class UserPaymentView(LoginRequiredMixin, StaffAccessMixin, UpdateSubscription):
    """UpdateSubscription with staff access control"""

    def get_object(self, queryset=None):
        username = self.kwargs.get("username")
        target_user = User.objects.get(username=username)
        return target_user.individual_organization
