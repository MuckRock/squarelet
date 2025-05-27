# Django
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Statistics(models.Model):
    """Nightly statistics"""

    date = models.DateField(
        unique=True, help_text=_("The date these statistics were taken")
    )

    total_users = models.IntegerField(
        help_text=_("The total number of users in the database")
    )
    total_users_excluding_agencies = models.IntegerField(
        help_text=_("The total number of users in the database excluding agency users")
    )
    total_users_pro = models.IntegerField(
        help_text=_("Total users who have a professional subscription")
    )
    total_users_org = models.IntegerField(
        help_text=_("Total users who have an organizational subscription")
    )

    total_users_mfa = models.IntegerField(
        help_text=_("Total users who have enabled MFA")
    )

    total_orgs = models.IntegerField(
        help_text=_(
            "The total number of organizations in the database excluding free "
            "individual organizations"
        )
    )
    verified_orgs = models.IntegerField(
        help_text=_("The number of organizations which are verified journalists")
    )

    users_today = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="+",
        help_text=_("Users who logged in on this date"),
    )
    pro_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="+",
        help_text=_("The users who had a professional account on this date"),
    )

    def __str__(self):
        return f"Stats for {self.date}"

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "statistics"
