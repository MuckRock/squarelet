# Django
from django.utils.translation import gettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class Category(DjangoChoices):
    candidates = ChoiceItem(0, _("Investigating Candidates"))
    polling = ChoiceItem(1, _("Polling"))
    data = ChoiceItem(2, _("Data"))
    guide = ChoiceItem(3, _("Voter Guide"))
    ops = ChoiceItem(4, _("Election Night Ops"))
    misinfo = ChoiceItem(5, _("Misinfo / Deepfakes"))
    violence = ChoiceItem(6, _("Violence"))
    training = ChoiceItem(7, _("Coverage Training / Coordination"))
    content = ChoiceItem(8, _("Content Sharing"))
    newsletters = ChoiceItem(9, _("Newsletters"))
