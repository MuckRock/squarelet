# Django
from django.db.models import signals
from django.dispatch import receiver

# Third Party
from actstream import registry

# Squarelet
from squarelet.organizations.models import (
    Invitation,
    Organization,
    Plan,
    ProfileChangeRequest,
)

# Register models with django-activity-stream
registry.register(Organization)
registry.register(ProfileChangeRequest)
registry.register(Invitation)


@receiver(
    signals.post_save,
    sender=Plan,
    dispatch_uid="squarelet.organizations.signals.make_stripe_plan",
)
def make_stripe_plan(sender, instance, created, raw, using, update_fields, **kwargs):
    """Create a stripe plan on plan creation"""
    # pylint: disable=unused-argument, too-many-positional-arguments
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
