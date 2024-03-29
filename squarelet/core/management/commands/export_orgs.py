# Django
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models.aggregates import Count

# Standard Library
import csv
from statistics import mode

# Third Party
from allauth.account.models import EmailAddress
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.organizations.models.organization import Organization


class Command(BaseCommand):
    """Export orgs"""

    def handle(self, *args, **kwargs):

        with smart_open(
            f"s3://{settings.AWS_STORAGE_BUCKET_NAME}/squarelet_export/orgs.csv", "w"
        ) as outfile:
            writer = csv.writer(outfile)
            writer.writerow(
                [
                    "name",
                    "uuid",
                    "verified",
                    "private",
                    "subtypes",
                    "email",
                    "common email domain",
                    "user count",
                    "plan",
                ]
            )
            orgs = (
                Organization.objects.filter(individual=False)
                .prefetch_related("subtypes", "plans")
                .annotate(user_count=Count("users"))
            )
            for org in orgs:
                subtypes = ", ".join(str(s) for s in org.subtypes.all())
                plans = ", ".join(str(p) for p in org.plans.all())
                email_domains = [
                    e.email.split("@")[1]
                    for e in EmailAddress.objects.filter(user__organizations=org)
                    if "@" in e.email
                ]
                domain = mode(email_domains) if email_domains else ""
                writer.writerow(
                    [
                        org.name,
                        org.uuid,
                        org.verified_journalist,
                        org.private,
                        subtypes,
                        org.email,
                        domain,
                        org.user_count,
                        plans,
                    ]
                )
