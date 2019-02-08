# Django
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.http import is_safe_url

# Third Party
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from furl import furl

# Squarelet
from squarelet.core.mail import Email


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def render_mail(self, template_prefix, email, context):
        """
        Renders an e-mail to `email`.  `template_prefix` identifies the
        e-mail that is to be sent, e.g. "account/email/email_confirmation"
        """
        subject = render_to_string(f"{template_prefix}_subject.txt", context)
        # remove superfluous line breaks
        subject = " ".join(subject.splitlines()).strip()
        # XXX do we want the [Squarelet] prefix?
        subject = self.format_email_subject(subject)

        return Email(
            subject=subject,
            template=f"{template_prefix}_message.html",
            to=[email],
            extra_context=context,
        )

    def is_safe_url(self, url):
        allowed_hosts = [
            furl(settings.SQUARELET_URL).host,
            furl(settings.MUCKROCK_URL).host,
            furl(settings.FOIAMACHINE_URL).host,
            furl(settings.DOCCLOUD_URL).host,
        ]
        return is_safe_url(url, allowed_hosts=allowed_hosts)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)
