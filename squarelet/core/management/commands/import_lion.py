# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Standard Library
import csv

# Third Party
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.organizations.choices import COUNTRY_CHOICES, STATE_CHOICES
from squarelet.organizations.models import (
    Organization,
    OrganizationSubtype,
    OrganizationType,
)

BUCKET = os.environ["IMPORT_BUCKET"]


class Command(BaseCommand):
    """Import organization data from LION member CSV"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry_run", action="store_true", help="Do not commit to database"
        )

    def handle(self, *args, **kwargs):
        dry_run = kwargs["dry_run"]

        with transaction.atomic():
            sid = transaction.savepoint()
            init_cache_invalidation_set()
            self.import_orgs()
            delete_cache_invalidation_set()
            if dry_run:
                self.stdout.write("Dry run, not commiting changes")
                transaction.savepoint_rollback(sid)

    def import_orgs(self):
        print(f"Begin Org Import {timezone.now()}")

        lion = Organization.objects.get(name="LION")
        local = OrganizationSubtype.objects.get(name="Local")
        online = OrganizationSubtype.objects.get(name="Online")

        with smart_open(f"s3://{BUCKET}/elections/lion.csv", "r") as infile, smart_open(
            f"s3://{BUCKET}/elections/lion_fuzzy.csv", "w"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            next(reader)  # discard headers
            for name, website, state, city, country in reader:
                try:
                    organization = Organization.objects.get(name=name)
                except Organization.DoesNotExist:
                    continue

                # add to lion
                lion.members.add(organization)
                # set city, state, country
                organization.city = city
                # get the state abbreviation
                states = [s[0] for s in STATE_CHOICES if s[1] == state]
                if len(states) == 0:
                    print(f"State not found: {state}")
                    continue
                organization.state = states[0]
                # get the country abbreviation
                if country == "United States":
                    country = "US"
                elif country == "Canada":
                    country = "CA"
                else:
                    print(f"Country not found: {country}")
                    continue
                organization.country = country

                organization.subtypes.add(local)
                organization.subtypes.add(online)

                if not website.startswith("http"):
                    website = "https://" + website
                organization.urls.update_or_create(url=website)

                organization.save()
