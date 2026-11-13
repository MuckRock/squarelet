import squarelet.organizations.models.payment
from django.core.files.base import ContentFile
from django.db import migrations, models
import django.db.models.deletion


# Products whose Service has another slug; the rest match by name.
PRODUCT_SERVICES = {"sunlight": "sunlight-research-desk"}

# Every page listing services renders its icon, and raises without one.
PLACEHOLDER_ICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"></svg>'
)


def product_to_service(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Service = apps.get_model("services", "Service")
    services = {s.slug: s for s in Service.objects.all()}
    for plan in Plan.objects.exclude(product=""):
        slug = PRODUCT_SERVICES.get(plan.product, plan.product)
        # The next operation drops `product`, so a plan left without a Service
        # would lose it for good.  The placeholder is filled in from the admin.
        if slug not in services:
            service = Service(
                slug=slug,
                name=slug.replace("-", " ").title(),
                provider_name="MuckRock",
            )
            service.icon.save(f"{slug}.svg", ContentFile(PLACEHOLDER_ICON))
            services[slug] = service
        plan.service = services[slug]
        plan.save(update_fields=["service"])


def service_to_product(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    products = {slug: product for product, slug in PRODUCT_SERVICES.items()}
    # Only these columns: a sibling branch may already have dropped others that
    # this state still lists.
    rows = Plan.objects.exclude(service=None).values_list("pk", "service__slug")
    for pk, slug in rows:
        Plan.objects.filter(pk=pk).update(product=products.get(slug, slug)[:20])


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0088_organization_nonprofit"),
        ("services", "0002_service_marketing_description_service_theme_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="icon",
            field=models.ImageField(
                blank=True,
                help_text="Icon for the plan",
                upload_to=squarelet.organizations.models.payment.plan_file_path,
                verbose_name="icon",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="service",
            field=models.ForeignKey(
                blank=True,
                help_text="Which service this plan is marketed under, for grouping tiers on the plan page.  This is a display label, not a description of what the plan grants - most plans span more than one service.  Do NOT use this to decide whether a plan switch is an upgrade; compare the entitlement client sets instead.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="plans",
                to="services.service",
                verbose_name="service",
            ),
        ),
        migrations.RunPython(product_to_service, service_to_product),
        migrations.RemoveField(
            model_name="plan",
            name="product",
        ),
    ]
