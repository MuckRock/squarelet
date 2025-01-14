# Django
from django.conf import settings
from django.contrib.auth import login
from django.contrib.sites.shortcuts import get_current_site
from django.http.response import HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

# Third Party
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from furl import furl

# Squarelet
from squarelet.core.mail import Email
from squarelet.organizations.models import Invitation
from squarelet.users.models import User
from squarelet.users.serializers import UserWriteSerializer


class AccountAdapter(DefaultAccountAdapter):
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
        #
        # if we were to add "presspass/" to the template_prefix here, the message
        # body template would become "presspass/presspass/etc/etc.html" in Email()
        subject_template = f"{template_prefix}_subject.txt"
        source = context.get("source") or "muckrock"
        if source == "presspass":
            subject_template = "presspass/" + subject_template

        subject = render_to_string(subject_template, context)
        # remove superfluous line breaks
        subject = " ".join(subject.splitlines()).strip()

        return Email(
            subject=subject,
            template=f"{template_prefix}_message.html",
            to=[email],
            extra_context=context,
            source=source,
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

    def login(self, request, user):
        """Check the session for a pending invitation before logging in,
        and if found assign it to the newly logged in user"""
        invitation_uuid = request.session.get("invitation")
        super().login(request, user)
        if invitation_uuid is not None and request.user.is_authenticated:
            Invitation.objects.filter(uuid=invitation_uuid).update(user=request.user)


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

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return
        # connect social account to currently logged in account
        if request.user.is_authenticated:
            user = request.user
        else:
            try:
                # if not logged in, try matching account based on email
                email = EmailAddress.objects.get(email=sociallogin.user.email)
                user = email.user
            except EmailAddress.DoesNotExist:
                return

        sociallogin.connect(request, user)
        login(
            request, user, backend="allauth.account.auth_backends.AuthenticationBackend"
        )
        response = HttpResponseRedirect(reverse("socialaccount_connections"))
        raise ImmediateHttpResponse(response)

    def save_user(self, request, sociallogin, form=None):
        """
        Saves a newly signed up social login. In case of auto-signup,
        the signup form is not available.
        """
        account = sociallogin.account
        user_data = {
            "username": UserWriteSerializer.unique_username(
                account.extra_data["login"]
            ),
            "email": account.extra_data["email"],
            "name": account.extra_data["name"],
            "source": "github",
        }
        user, _, _ = User.objects.register_user(user_data)
        sociallogin.user = user
        sociallogin.save(request)
        return user
