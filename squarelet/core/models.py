"""Misc database utilities"""
import os

# Django
from django.db.models import Func
from django.db.models.expressions import Value


class Interval(Func):
    """PostgreSQL interval type"""

    # pylint: disable=abstract-method

    template = "interval %(expressions)s"

    def __init__(self, expression, **extra):
        super().__init__(Value(expression), **extra)

# Airtable Models
from pyairtable.orm import Model, fields as F

class Provider(Model):
    name = F.TextField("Name")
    logo = F.AttachmentsField("Logo")
    url = F.UrlField("URL")
    verified = F.CheckboxField("Verified")

    class Meta:
      api_key = os.environ['AIRTABLE_ACCESS_TOKEN']
      base_id = os.environ['AIRTABLE_ERH_BASE_ID']
      table_name = "Providers"

class Resource(Model):
    uid = F.AutoNumberField("ID")
    name = F.TextField("Name")
    shortDescription = F.TextField("Short Description")
    logo = F.AttachmentsField("Logo")
    provider = F.LinkField("Provider", Provider)
    status = F.SelectField("Status")
    visible = F.SelectField("Show?")
    cost = F.SelectField("Cost")
    homepageUrl = F.UrlField("Homepage URL")
    accessUrl = F.UrlField("Access URL")
    category = F.MultipleSelectField("Category")

    class Meta:
      api_key = os.environ['AIRTABLE_ACCESS_TOKEN']
      base_id = os.environ['AIRTABLE_ERH_BASE_ID']
      table_name = "Resources"