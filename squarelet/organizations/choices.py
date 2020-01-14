# Django
from django.utils.translation import ugettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class ChangeLogReason(DjangoChoices):
    # pylint: disable=no-init
    created = ChoiceItem(0, _("Created"))
    updated = ChoiceItem(0, _("Updated"))
    failed = ChoiceItem(0, _("Failed"))


class StripeAccounts(DjangoChoices):
    # pylint: disable=no-init
    muckrock = ChoiceItem(0, _("MuckRock"))
    presspass = ChoiceItem(1, _("PressPass"))
