# Django
from django.conf import settings
from django.db import models


class Statistics(models.Model):
    """Nightly statistics"""

    # pylint: disable=invalid-name
    date = models.DateField(unique=True)

    total_users = models.IntegerField()
    total_users_excluding_agencies = models.IntegerField()
    total_users_pro = models.IntegerField()
    total_users_org = models.IntegerField()

    total_orgs = models.IntegerField()

    users_today = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+")
    pro_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+")

    def __str__(self):
        return "Stats for %s" % self.date

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "statistics"
