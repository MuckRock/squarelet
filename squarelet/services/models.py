from django.db import models
from squarelet.core.utils import file_path


def service_file_path(instance, filename):
    return file_path("service_icons", instance, filename)


class Service(models.Model):
    slug = models.SlugField(
        unique=True, max_length=100, help_text="URL-friendly name for the service"
    )
    name = models.CharField(max_length=255, help_text="Display name of the service")
    icon = models.ImageField(
        upload_to=service_file_path, help_text="Icon for the service"
    )
    description = models.TextField(help_text="Short description of the service")
    provider_name = models.CharField(
        max_length=255, help_text="Name of the service provider/maintainer"
    )
    base_url = models.URLField(
        null=True,
        blank=True,
        max_length=255,
        help_text="Base URL for the service (e.g. https://www.muckrock.com)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
