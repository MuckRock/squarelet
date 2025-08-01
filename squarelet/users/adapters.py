# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.sites.shortcuts import get_current_site
from django.http.response import HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _

# Third Party
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.signals import user_logged_in
from allauth.account.utils import get_login_redirect_url
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from furl import furl

# Squarelet
from squarelet.core.mail import Email
from squarelet.organizations.models import Invitation


class AccountAdapter(DefaultAccountAdapter):
    """
    Custom account adapter for allauth
    """

    def can_delete_email(self, email_address):
        """Do not allow somone to delete their primary email address"""
        if email_address.primary:
            return False
        return super().can_delete_email(email_address)

    def is_open_for_signup(self, request):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def render_mail(self, template_prefix, email, context, headers=None):
        """
        Renders an e-mail to `email`.  `template_prefix` identifies the
        e-mail that is to be sent, e.g. "account/email/email_confirmation"
        """

        # we need to prefix the subject template here because it's getting
        # rendered here; the actual email body template is rendered in the
        # Email class, which also fixes the template prefix
        subject_template = f"{template_prefix}_subject.txt"

        subject = render_to_string(subject_template, context)
        # remove superfluous line breaks
        subject = " ".join(subject.splitlines()).strip()

        return Email(
            subject=subject,
            template=f"{template_prefix}_message.html",
            to=[email],
            extra_context=context,
            headers=headers,
        )

    def is_safe_url(self, url):
        allowed_hosts = [
            furl(settings.SQUARELET_URL).host,
            furl(settings.MUCKROCK_URL).host,
            furl(settings.FOIAMACHINE_URL).host,
            furl(settings.DOCCLOUD_URL).host,
            furl(settings.PRESSPASS_URL).host,
            furl(settings.BIGLOCALNEWS_URL).host,
            furl(settings.BIGLOCALNEWS_API_URL).host,
            furl(settings.AGENDAWATCH_URL).host,
        ]
        return url_has_allowed_host_and_scheme(url, allowed_hosts=allowed_hosts)

    def send_confirmation_mail(self, request, emailconfirmation, signup):
        current_site = get_current_site(request)

        activate_url = self.get_email_confirmation_url(request, emailconfirmation)

        source_site = request.get_host()

        ctx = {
            "user": emailconfirmation.email_address.user,
            "email": emailconfirmation.email_address.email,
            "activate_url": activate_url,
            "current_site": current_site,
            "key": emailconfirmation.key,
            "source": "muckrock",
        }
        if source_site == furl(settings.PRESSPASS_API_URL).host:
            ctx["source"] = "presspass"
            ctx["activate_url"] = (
                f"{settings.PRESSPASS_URL}/#/profile/welcome/{emailconfirmation.key}"
            )

        if signup:
            email_template = "account/email/email_confirmation_signup"
        else:
            email_template = "account/email/email_confirmation"

        self.send_mail(email_template, emailconfirmation.email_address.email, ctx)

    def get_email_verification_redirect_url(self, email_address):
        """
        Return the user to the onboarding flow if they are partway through it.
        Return to the default URL otherwise.
        """
        return reverse("account_onboarding")

    def login(self, request, user):
        """Check the session for a pending invitation before logging in,
        and if found assign it to the newly logged in user"""
        invitation_uuid = request.session.get("invitation")
        super().login(request, user)
        if invitation_uuid is not None and request.user.is_authenticated:
            Invitation.objects.filter(uuid=invitation_uuid).update(user=request.user)

    def post_login(
        self,
        request,
        user,
        *,
        email_verification,
        signal_kwargs,
        email,
        signup,
        redirect_url,
    ):
        """
        Extend the post_login method to perform onboarding checks
        """

        # Get the default redirect URL (which honors the 'next' parameter)
        original_redirect = get_login_redirect_url(request, redirect_url, signup=signup)

        # Store the redirect URL and other params in the session for later use
        request.session["next_url"] = original_redirect
        request.session["checkFor"] = request.GET.get("checkFor")
        request.session["intent"] = request.GET.get("intent")

        # Check if we need user to go through onboarding
        requires_onboarding = True  # TODO: Actually check lol

        if requires_onboarding:
            # Pass the user to the onboarding view
            response = HttpResponseRedirect(reverse("account_onboarding"))
        else:
            # Use the original redirect
            response = HttpResponseRedirect(original_redirect)

        if signal_kwargs is None:
            signal_kwargs = {}
        # Send the user_logged_in signal
        user_logged_in.send(
            sender=user.__class__,
            request=request,
            response=response,
            user=user,
            **signal_kwargs,
        )
        # Add a success message
        self.add_message(
            request,
            messages.SUCCESS,
            "account/messages/logged_in.txt",
            {"user": user},
        )
        return response

    def get_user_search_fields(self):
        return []


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def authentication_error(
        self, request, provider_id, error=None, exception=None, extra_context=None
    ):
        print(
            "SocialAccount authentication error!",
            "error",
            request,
            {
                "provider_id": provider_id,
                "error": str(error),
                "exception": str(exception),
                "extra_context": extra_context,
            },
        )

    def save_user(self, request, sociallogin, form=None):
        """
        Saves a newly signed up social login. In case of auto-signup,
        the signup form is not available.
        """
        # we do not allow auto-signup so form should be present
        user = form.save(request, setup_email=False)
        sociallogin.user = user
        sociallogin.save(request)
        return user

    def get_signup_form_initial_data(self, sociallogin):
        initial = super().get_signup_form_initial_data(sociallogin)
        initial["name"] = f"{initial['first_name']} {initial['last_name']}"
        return initial


class MfaAdapter(DefaultMFAAdapter):
    error_messages = {
        "add_email_blocked": _(
            "You cannot add an email address to an account "
            "protected by two-factor authentication."
        ),
        "cannot_delete_authenticator": _(
            "You cannot deactivate two-factor authentication."
        ),
        "cannot_generate_recovery_codes": _(
            "You cannot generate recovery codes without "
            "having two-factor authentication enabled."
        ),
        "unverified_email": _(
            "All email addresses associated with your account "
            "must be confirmed before enabling two-factor authentication."
        ),
        "incorrect_code": _("Incorrect code."),
    }
