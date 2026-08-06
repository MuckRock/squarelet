# Generated manually

from django.db import migrations


def forwards(apps, schema_editor):
    Customer = apps.get_model("organizations", "Customer")
    PaymentMethod = apps.get_model(
        "organizations", "PaymentMethod"
    )

    customers = Customer.objects.exclude(
        stripe_payment_method_id=""
    )
    payment_methods = []
    for customer in customers.iterator():
        payment_methods.append(
            PaymentMethod(
                customer=customer,
                method_type="card",
                brand=customer.payment_brand,
                last4=customer.payment_last4,
                exp_month=customer.payment_exp_month,
                exp_year=customer.payment_exp_year,
                stripe_id=customer.stripe_payment_method_id,
                is_default=True,
            )
        )
    if payment_methods:
        PaymentMethod.objects.bulk_create(payment_methods)


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0074_paymentmethod"),
    ]

    operations = [
        migrations.RunPython(
            forwards, migrations.RunPython.noop
        ),
    ]
