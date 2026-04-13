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

# Register models with django-activity-stream
registry.register(Organization)
registry.register(ProfileChangeRequest)
registry.register(Invitation)

# pylint:disable=too-many-positional-arguments


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
    signals.m2m_changed,
    sender=Organization.members.through,
    dispatch_uid="squarelet.organizations.signals.sync_wix_on_member_add",
)
def sync_wix_on_member_add(sender, instance, action, pk_set, reverse, **kwargs):
    """Trigger Wix sync when a member org is added to a group's members M2M.

    This covers the case where staff directly assigns a ChildOrg to a ParentOrg
    via the Django admin (bypassing the OrganizationInvitation flow).

    For a self-referential M2M two directions are possible:
    - Forward  (reverse=False): group.members.add(member_org)
        instance=group, pk_set={member_org.pk}
    - Reverse  (reverse=True):  member_org.groups.add(group)
        instance=member_org, pk_set={group.pk}
    """
    # pylint: disable=unused-argument
    if action != "post_add" or not pk_set:
        return

    # Import here to avoid circular imports
    # pylint: disable=import-outside-toplevel
    from squarelet.organizations.tasks import sync_wix_for_group_member

    if not reverse:
        # Forward: instance is the group, pk_set contains added member org PKs
        group = instance
        if not (group.share_resources and group.plan and group.plan.wix):
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
        # Reverse: instance is the member org, pk_set contains group PKs it joined
        member_org = instance
        member_pk = member_org.pk
        for group_pk in pk_set:
            group = Organization.objects.filter(pk=group_pk).select_related("_plan").first()
            if group and group.share_resources and group.plan and group.plan.wix:
                plan_pk = group.plan.pk
                transaction.on_commit(
                    lambda g=group_pk, p=plan_pk: sync_wix_for_group_member.delay(
                        member_pk, g, p
                    )
                )
