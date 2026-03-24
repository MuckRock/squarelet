"""Data migration to populate the `hidden` field on Organization.

- Non-individual orgs: hidden=False (they don't use the hidden field).
- Individual orgs: private=False (public by default going forward).
- Individual orgs are un-hidden (hidden=False) if any of:
    - The user has at least one verified primary email.
    - The organization has any Charge.
    - The user belongs to a verified_journalist org.
- All other individual orgs remain hidden=True.
"""

from django.db import migrations, models


def populate_hidden(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    EmailAddress = apps.get_model("account", "EmailAddress")
    Charge = apps.get_model("organizations", "Charge")

    # Non-individual orgs: hidden=False
    Organization.objects.filter(individual=False).update(hidden=False)

    # Individual orgs: set private=False (public by default)

    # Un-hide individual orgs whose user has a verified primary email
    has_verified_email = EmailAddress.objects.filter(
        verified=True,
        primary=True,
    ).values_list("user_id", flat=True)
    Organization.objects.filter(
        individual=True,
        users__in=has_verified_email,
    ).update(hidden=False)

    # Un-hide individual orgs that have any charge
    has_charges = Charge.objects.values_list("organization_id", flat=True).distinct()
    Organization.objects.filter(
        individual=True,
        pk__in=has_charges,
    ).update(hidden=False)

    # Un-hide individual orgs whose user belongs to a verified_journalist org
    verified_journalist_member_ids = Organization.objects.filter(
        verified_journalist=True
    ).values_list("users__pk", flat=True)
    Organization.objects.filter(
        individual=True,
        users__in=verified_journalist_member_ids,
    ).update(hidden=False)


def reverse_populate_hidden(apps, schema_editor):
    """Reverse: reset all orgs to hidden=True, private=True for individuals."""
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.all().update(hidden=True)
    Organization.objects.filter(individual=True).update(private=True)


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0059_add_hidden"),
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_hidden, reverse_populate_hidden),
    ]
