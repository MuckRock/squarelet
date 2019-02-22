# Django
from django.contrib.auth.models import User
from django.db import models


# Create your models here.

# XXX stats

"""
total users
total users less agency users

pro users count
pro users for that day

total org members
total active orgs
"""


class Statistics(models.Model):
    """Nightly statistics"""

    # pylint: disable=invalid-name
    date = models.DateField(unique=True)

    total_users = models.IntegerField()
    total_users_excluding_agencies = models.IntegerField()
    total_users_pro = models.IntegerField()
    total_users_org = models.IntegerField()

    total_orgs = models.IntegerField()

    users_today = models.ManyToManyField(User)
    pro_users = models.ManyToManyField(User)

    def __str__(self):
        return "Stats for %s" % self.date

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "statistics"
