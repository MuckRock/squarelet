# Django
from django.conf import settings
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string

# Standard Library
import logging

# Third Party
from html2text import html2text

ORG_TO_ALL = 0
ORG_TO_ADMINS = 1
ORG_TO_RECEIPTS = 2

logger = logging.getLogger(__name__)


class Email(EmailMultiAlternatives):
    """Custom email class to handle our transactional email"""

    template = None

    def __init__(self, **kwargs):
        user = kwargs.pop("user", None)
        organization = kwargs.pop("organization", None)
        organization_to = kwargs.pop("organization_to", ORG_TO_ALL)
        extra_context = kwargs.pop("extra_context", {})
        template = kwargs.pop("template", self.template)
        super().__init__(**kwargs)
        # set up who we are sending the email to
        if user and organization:
            raise ValueError("Supply only one of userand organization")
        if user:
            self.to.append(user.email)
        if organization and organization_to == ORG_TO_ADMINS:
            self.to.extend(
                [
                    m.user.email
                    for m in organization.memberships.select_related("user").filter(
                        admin=True
                    )
                ]
            )
        elif organization and organization_to == ORG_TO_RECEIPTS:
            self.to.extend([r.email for r in organization.receipt_emails.all()])
        elif organization and organization_to == ORG_TO_ALL:
            self.to.extend([u.email for u in organization.users.all()])

        if not self.to:
            logger.warning(
                "Email created with no receipients - "
                "User: %s, Organization: %s, Organization To: %d, Subject: %s",
                user,
                organization,
                organization_to,
                self.subject,
            )
        # always BCC diagnostics
        self.bcc.append("diagnostics@muckrock.com")

        context = {
            "base_url": settings.SQUARELET_URL,
            "subject": self.subject,
            "user": user,
            "organization": organization,
        }
        context.update(extra_context)
        html = render_to_string(template, context)
        plain = html2text(html)
        self.body = plain
        self.attach_alternative(html, "text/html")

    def send(self, fail_silently=False):
        if self.to:
            super().send(fail_silently)
        else:
            logger.warning(
                "Refusing to send email with no recipients: %s", self.subject
            )


def send_mail(**kwargs):
    email = Email(**kwargs)
    email.send()
