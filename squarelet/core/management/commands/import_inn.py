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
    """Import organization data from INN member CSV"""

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
        # pylint: disable=too-many-locals, too-many-statements
        print(f"Begin Org Import {timezone.now()}")

        inn = Organization.objects.get(name="INN")
        nonprofit = OrganizationSubtype.objects.get(name="Nonprofit")
        reaches = ["Local", "State", "Regional", "National", "Global"]
        reach_map = {r: OrganizationSubtype.objects.get(name=r) for r in reaches}

        all_organizations = Organization.objects.filter(individual=False)

        total = 0
        exact = 0
        fuzzy = 0
        multiple = 0
        mapped = 0

        org_map = {}

        with smart_open(f"s3://{BUCKET}/elections/inn_map.csv", "r") as infile:
            reader = csv.reader(infile)
            next(reader)
            for inn_name, sq_name in reader:
                org_map[inn_name] = sq_name

        with smart_open(f"s3://{BUCKET}/elections/inn.csv", "r") as infile, smart_open(
            f"s3://{BUCKET}/elections/inn_fuzzy.csv", "w"
        ) as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            writer.writerow(["inn org", "squarelet org", "squarelet link", "score"])
            next(reader)  # discard headers
            for co_name, pub_name, website, reach, city, state in reader:
                total += 1
                organizations = Organization.objects.filter(
                    individual=False, name__in=[co_name, pub_name]
                )
                if len(organizations) == 1:
                    organization = organizations[0]
                    exact += 1
                elif len(organizations) > 1:
                    print(f"Multiple matches: {co_name}")
                    for organization in organizations:
                        writer.writerow(
                            [
                                co_name,
                                organization.name,
                                "https://accounts.muckrock.com"
                                + organization.get_absolute_url(),
                                "multiple match",
                            ]
                        )
                    multiple += 1
                    continue
                elif len(organizations) == 0:
                    if co_name in org_map:
                        try:
                            organization = Organization.objects.get(
                                name=org_map[co_name]
                            )
                        except (
                            Organization.DoesNotExist,
                            Organization.MultipleObjectsReturned,
                        ) as exc:
                            print(f"Error: {exc} - {co_name} - {org_map[co_name]}")
                            continue
                        mapped += 1
                    else:
                        co_match = process.extractOne(
                            co_name,
                            {o: o.name for o in all_organizations},
                            scorer=fuzz.ratio,
                            score_cutoff=83,
                        )
                        pub_match = process.extractOne(
                            pub_name,
                            {o: o.name for o in organizations},
                            scorer=fuzz.ratio,
                            score_cutoff=83,
                        )
                        matches = [m for m in [co_match, pub_match] if m is not None]
                        if matches:
                            # get the higher match
                            matches.sort(key=lambda x: x[1], reverse=True)
                            fuzzy += 1
                            org_name, score, match_org = matches[0]
                            writer.writerow(
                                [
                                    co_name,
                                    org_name,
                                    "https://accounts.muckrock.com"
                                    + match_org.get_absolute_url(),
                                    score,
                                ]
                            )
                        continue

                # add to lion
                inn.members.add(organization)
                # set city, state, country
                organization.city = city
                organization.state = state
                organization.country = "US"

                organization.subtypes.add(nonprofit)
                organization.subtypes.add(reach_map[reach])

                if not website.startswith("http"):
                    website = "https://" + website
                organization.urls.update_or_create(url=website)

                organization.save()

        print(
            f"End Org Import {timezone.now()} - Total: {total} "
            f"Exact: {exact} Fuzzy: {fuzzy} Multiple: {multiple}"
        )
