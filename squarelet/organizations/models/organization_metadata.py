# Django
from django.db import models
from django.utils.translation import gettext_lazy as _


class OrganizationType(models.Model):
    """A broad type an organization may be classified as"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The name of the organization type")
    )

    def __str__(self):
        return self.name


class OrganizationSubtype(models.Model):
    """A specific type an organization may be classified as"""

    name = models.CharField(
        _("name"), max_length=255, help_text=_("The name of the organization subtype")
    )
    type = models.ForeignKey(
        verbose_name=_("type"),
        to="organizations.OrganizationType",
        on_delete=models.PROTECT,
        related_name="subtypes",
        help_text=_("The parent type for this subtype"),
    )

    class Meta:
        ordering = ("type",)

    def __str__(self):
        return f"{self.type.name} - {self.name}"


class OrganizationUrl(models.Model):
    """URLs associated with an organization"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="urls",
        help_text=_("The organization to associate the URL with"),
    )
    url = models.URLField(_("url"))


class OrganizationEmailDomain(models.Model):
    """Email Domains associated with an organization"""

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="domains",
        help_text=_("The organization to associate the email domain with"),
    )
    domain = models.CharField(_("domain"), max_length=255)
