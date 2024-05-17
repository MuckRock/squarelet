# Django
from django.db import models
from django.utils.translation import gettext_lazy as _

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.elections.choices import Category


class ElectionResource(models.Model):
    """An election resource available to journalists"""

    name = models.CharField(
        _("name"),
        help_text=_("The name of the resource"),
    )
    source = models.CharField(
        _("source"),
        help_text=_("Who contributed the resource"),
    )
    category = models.IntegerField(
        _("category"),
        choices=Category.choices,
        help_text=("The category of the resource"),
    )
    description = models.TextField(
        _("description"),
        help_text=_("A brief description of the resource"),
    )
    url = models.URLField(
        _("url"),
        help_text=_("The URL where the resource can be accessed"),
    )
    active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Should this resource be shown"),
    )

    subtypes = models.ManyToManyField(
        verbose_name=_("subtypes"),
        to="organizations.OrganizationSubtype",
        related_name="resources",
        help_text=_("The organization subtypes which may access this resource"),
        blank=True,
    )
    members = models.ManyToManyField(
        verbose_name=_("members"),
        to="organizations.Organization",
        related_name="resources",
        help_text=_(
            "Organizations which are a member of this organization "
            "may access this resource"
        ),
        limit_choices_to={"individual": False},
        blank=True,
    )

    created_at = AutoCreatedField(
        _("created at"),
        help_text=_("When this resource was created"),
    )
    updated_at = AutoLastModifiedField(
        _("updated at"),
        help_text=_("When this resource was last updated"),
    )

    def __str__(self):
        return self.name
