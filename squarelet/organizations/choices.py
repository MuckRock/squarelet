# Django
from django.utils.translation import ugettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class OrgType(DjangoChoices):
    free = ChoiceItem(0, _("Free"))
    pro = ChoiceItem(1, _("Pro"))
    basic = ChoiceItem(2, _("Basic"))
    plus = ChoiceItem(3, _("Plus"))

    @classmethod
    def _choices_subset(cls, values):
        return [(v, l) for v, l in cls.choices if v in values]

    @classmethod
    def individual_choices(cls):
        return cls._choices_subset([cls.free, cls.pro])

    @classmethod
    def group_choices(cls):
        return cls._choices_subset([cls.free, cls.basic, cls.plus])
