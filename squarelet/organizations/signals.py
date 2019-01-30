# Django
from django.db.models import signals
from django.dispatch import receiver

# Squarelet
from squarelet.organizations.models import Plan


@receiver(
    signals.post_save,
    sender=Plan,
    dispatch_uid="squarelet.organizations.signals.make_stripe_plan",
)
def make_stripe_plan(sender, instance, created, raw, using, update_fields, **kwargs):
    """Create a stripe plan on plan creation"""
    # pylint: disable=too-many-arguments, unused-argument
    if created:
        instance.make_stripe_plan()


@receiver(
    signals.pre_delete,
    sender=Plan,
    dispatch_uid="squarelet.organizations.signals.delete_stripe_plan",
)
def delete_stripe_plan(sender, instance, using, **kwargs):
    """Create a stripe plan on plan creation"""
    # pylint: disable=unused-argument
    instance.delete_stripe_plan()
