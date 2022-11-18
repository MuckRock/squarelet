# Django
from django.utils.translation import gettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class ChangeLogReason(DjangoChoices):
    created = ChoiceItem(0, _("Created"))
    updated = ChoiceItem(0, _("Updated"))
    failed = ChoiceItem(0, _("Failed"))
