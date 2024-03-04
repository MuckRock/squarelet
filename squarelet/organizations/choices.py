# Django
from django.utils.translation import gettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class ChangeLogReason(DjangoChoices):
    created = ChoiceItem(0, _("Created"))
    updated = ChoiceItem(1, _("Updated"))
    failed = ChoiceItem(2, _("Failed"))
    credit_card = ChoiceItem(3, _("Credit Card"))
