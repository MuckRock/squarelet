"""Misc database utilities"""

# Django
from django.conf import settings
from django.db.models import Func
from django.db.models.expressions import Value

# Third Party
# Airtable Models
from pyairtable.orm import Model, fields as F


class Interval(Func):
    """PostgreSQL interval type"""

    # pylint: disable=abstract-method

    template = "interval %(expressions)s"

    def __init__(self, expression, **extra):
        super().__init__(Value(expression), **extra)


class Alert(Model):
    uid = F.AutoNumberField("ID")
    message = F.RichTextField("Message")
    expiration_date = F.DatetimeField("Expiration Date")
    segment = F.SelectField("Segment")
    status = F.SelectField("Status")

    class Meta:
        api_key = settings.AIRTABLE_ACCESS_TOKEN
        base_id = settings.AIRTABLE_ERH_BASE_ID
        table_name = "Alerts"


class Provider(Model):
    name = F.TextField("Name")
    logo = F.AttachmentsField("Logo")
    url = F.UrlField("URL")
    verified = F.CheckboxField("Verified")

    class Meta:
        api_key = settings.AIRTABLE_ACCESS_TOKEN
        base_id = settings.AIRTABLE_ERH_BASE_ID
        table_name = "Providers"


class Resource(Model):
    uid = F.AutoNumberField("ID")
    name = F.TextField("Name")
    shortDescription = F.TextField("Short Description")
    logo = F.AttachmentsField("Logo")
    provider_name = F.TextField("Provider Name")
    provider_id = F.TextField("Provider ID")
    status = F.SelectField("Status")
    visible = F.SelectField("Show?")
    cost = F.SelectField("Cost")
    expiration_date = F.DatetimeField("Expiration Date")
    homepageUrl = F.UrlField("Homepage URL")
    accessUrl = F.UrlField("Access URL")
    category = F.MultipleSelectField("Category")
    categories = F.LinkField("Categories", "Category")
    longDescription = F.RichTextField("Long Description")
    screenshots = F.AttachmentsField("Screenshots")

    class Meta:
        api_key = settings.AIRTABLE_ACCESS_TOKEN
        base_id = settings.AIRTABLE_ERH_BASE_ID
        table_name = "Resources"


class Category(Model):
    name = F.TextField("Name")
    description = F.TextField("Description")
    resources = F.LinkField("Resources", Resource)

    class Meta:
        api_key = settings.AIRTABLE_ACCESS_TOKEN
        base_id = settings.AIRTABLE_ERH_BASE_ID
        table_name = "Categories"


class NewsletterSignup(Model):
    email = F.EmailField("Email")
    name = F.TextField("Name")
    organization = F.TextField("Organization")

    class Meta:
        api_key = settings.AIRTABLE_ACCESS_TOKEN
        base_id = "appMhNUZlHMCis47k"
        table_name = "Email Subscribers"
