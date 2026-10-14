import squarelet.organizations.models.payment
from django.db import migrations, models
import django.db.models.deletion


def product_to_service(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Service = apps.get_model("services", "Service")
    services = {s.slug: s for s in Service.objects.all()}
    for plan in Plan.objects.exclude(product=""):
        service = services.get(plan.product)
        if service is not None:
            plan.service = service
            plan.save(update_fields=["service"])


def service_to_product(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    for plan in Plan.objects.exclude(service=None).select_related("service"):
        plan.product = plan.service.slug[:20]
        plan.save(update_fields=["product"])


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
