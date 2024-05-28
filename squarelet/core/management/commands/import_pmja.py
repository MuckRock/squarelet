# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Standard Library
import csv
import os

# Third Party
from fuzzywuzzy import fuzz, process
from smart_open.smart_open_lib import smart_open

# Squarelet
from squarelet.oidc.middleware import (
    delete_cache_invalidation_set,
    init_cache_invalidation_set,
)
from squarelet.organizations.models import Organization, OrganizationSubtype

BUCKET = os.environ["IMPORT_BUCKET"]


class Command(BaseCommand):
    """Import organization data from PMJA member CSV"""

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
        # pylint: disable=too-many-locals
        print(f"Begin Org Import {timezone.now()}")

        pmja = Organization.objects.get(name="PMJA")
        nonprofit = OrganizationSubtype.objects.get(name="Nonprofit")
        radio = OrganizationSubtype.objects.get(name="Radio")
        television = OrganizationSubtype.objects.get(name="Television")
        organizations = Organization.objects.filter(individual=False)

        total = 0
        exact = 0
        fuzzy = 0

        with smart_open(f"s3://{BUCKET}/elections/pmja.csv", "r") as infile, smart_open(
            f"s3://{BUCKET}/elections/pmja_fuzzy.csv", "w"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            writer.writerow(["pmja org", "squarelet org", "squarelet link"])
            next(reader)  # discard headers
            for name, city, state, _zip_code, website in reader:
                total += 1
                try:
                    organization = Organization.objects.get(name=name)
                except Organization.DoesNotExist:
                    match = process.extractOne(
                        name,
                        {o: o.name for o in organizations},
                        scorer=fuzz.partial_ratio,
                        score_cutoff=83,
                    )
                    if match:
                        fuzzy += 1
                        org_name, _score, match_org = match
                        writer.writerow([name, org_name, match_org.get_absolute_url()])
                    continue

                exact += 1

                # add to pmja
                pmja.members.add(organization)
                # set city, state, country
                organization.city = city
                organization.state = state
                organization.country = "US"

                organization.subtypes.add(nonprofit)
                organization.subtypes.add(radio)
                organization.subtypes.add(television)

                if not website.startswith("http"):
                    website = "https://" + website
                organization.urls.update_or_create(url=website)

                organization.save()

        print(
            f"End Org Import {timezone.now()} - Total: {total} "
            f"Exact: {exact} Fuzzy: {fuzzy}"
        )
