# Django
from django import forms
from django.core.validators import validate_email
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

# Standard Library
import re

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
        super().__init__(*args, **kwargs)


class AutoLastModifiedField(AutoCreatedField):
    """
    A DateTimeField that updates itself on each save() of the model.
    By default, sets editable=False and default=datetime.now.
    """

    def pre_save(self, model_instance, add): #pylint: disable = unused-argument
        value = now()
        setattr(model_instance, self.attname, value)
        return value


class EmailsListField(forms.CharField):
    """Multi email field"""

    widget = forms.Textarea
    # separate emails by whitespace or commas
    email_separator_re = re.compile(r"[\s,]+")

    def clean(self, value):
        """Validates list of email addresses"""
        super().clean(value)

        emails = self.email_separator_re.split(value)

        if not emails:
            raise forms.ValidationError(_("Enter at least one e-mail address."))

        for email in emails:
            validate_email(email)

        return emails
