# Django
from django.db import transaction
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
from squarelet.organizations.tasks import sync_wix_for_group_member

# Register models with django-activity-stream
registry.register(Organization)
registry.register(ProfileChangeRequest)
registry.register(Invitation)

# pylint:disable=too-many-positional-arguments


def should_sync_wix(org):
    """Should we sync this org with Wix?"""
    return org and org.share_resources and org.plan and org.plan.wix


@receiver(
    signals.post_save,
    sender=Plan,
    dispatch_uid="squarelet.organizations.signals.make_stripe_plan",
)
def make_stripe_plan(sender, instance, created, raw, using, update_fields, **kwargs):
    """Create a stripe plan on plan creation"""
    # pylint: disable=unused-argument
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


@receiver(
    signals.pre_save,
    sender=Organization,
    dispatch_uid="squarelet.organizations.signals.track_parent_change",
)
def track_parent_change(sender, instance, **kwargs):
    """Stash the previous parent_id so post_save can detect changes."""
    # pylint: disable=unused-argument,protected-access
    if instance.pk:
        try:
            instance._previous_parent_id = (
                Organization.objects.filter(pk=instance.pk)
                .values_list("parent_id", flat=True)
                .get()
            )
        except Organization.DoesNotExist:
            instance._previous_parent_id = None
    else:
        instance._previous_parent_id = None


@receiver(
    signals.post_save,
    sender=Organization,
    dispatch_uid="squarelet.organizations.signals.sync_wix_on_parent_change",
)
def sync_wix_on_parent_change(sender, instance, **kwargs):
    """Trigger Wix sync when a child org's parent FK is set or changed to a
    resource-sharing parent with a Wix plan.

    This covers the case where staff sets the parent directly via Django admin
    (bypassing the OrganizationInvitation flow).
    """
    # pylint: disable=unused-argument
    if instance.parent_id == getattr(instance, "_previous_parent_id", None):
        return

    parent = instance.parent
    if not should_sync_wix(parent):
        return

    child_pk = instance.pk
    parent_pk = parent.pk
    plan_pk = parent.plan.pk
    transaction.on_commit(
        lambda: sync_wix_for_group_member.delay(child_pk, parent_pk, plan_pk)
    )


@receiver(
    signals.m2m_changed,
    sender=Organization.members.through,
    dispatch_uid="squarelet.organizations.signals.sync_wix_on_member_add",
)
def sync_wix_on_member_add(sender, instance, action, pk_set, reverse, **kwargs):
    """Trigger Wix sync when a member org is added to a group's members M2M.

    This covers the case where staff directly assigns a ChildOrg to a ParentOrg
    via the Django admin (bypassing the OrganizationInvitation flow).

    - For forward relationships (reverse=False), the instance is the group
      and the pk_set contains added member org PKs.
    - For reverse relationships (reverse=True), the instances is the member_org,
      and the pk_set contains group PKs it joined.
    """
    # pylint: disable=unused-argument
    if action != "post_add" or not pk_set:
        return

    if not reverse:
        group = instance
        if not should_sync_wix(group):
            return
        group_pk = group.pk
        plan_pk = group.plan.pk
        for member_pk in pk_set:
            transaction.on_commit(
                lambda m=member_pk: sync_wix_for_group_member.delay(
                    m, group_pk, plan_pk
                )
            )
    else:
        member_org = instance
        member_pk = member_org.pk
        for group_pk in pk_set:
            group = (
                Organization.objects.filter(pk=group_pk).select_related("_plan").first()
            )
            if should_sync_wix(group):
                plan_pk = group.plan.pk
                transaction.on_commit(
                    lambda g=group_pk, p=plan_pk: sync_wix_for_group_member.delay(
                        member_pk, g, p
                    )
                )
