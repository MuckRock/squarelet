# Django
from django.db import models
from django.utils.timezone import now

# taken from:
# https://github.com/jazzband/django-model-utils


class AutoCreatedField(models.DateTimeField):
    """
    A DateTimeField that automatically populates itself at
    object creation.
    By default, sets editable=False, default=datetime.now.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("editable", False)
        kwargs.setdefault("default", now)
        super(AutoCreatedField, self).__init__(*args, **kwargs)


class AutoLastModifiedField(AutoCreatedField):
    """
    A DateTimeField that updates itself on each save() of the model.
    By default, sets editable=False and default=datetime.now.
    """

    def pre_save(self, model_instance, add):
        value = now()
        setattr(model_instance, self.attname, value)
        return value


class AliasField(models.Field):
    """Virtual field
    https://stackoverflow.com/a/46995564
    """

    def contribute_to_class(self, cls, name, private_only=False):
        super(AliasField, self).contribute_to_class(cls, name, private_only=True)
        setattr(cls, name, self)

    def __get__(self, instance, instance_type=None):
        return getattr(instance, self.db_column)
