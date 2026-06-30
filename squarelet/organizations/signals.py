# Django
from django.db import transaction
from django.db.models import signals
from django.dispatch import receiver

# Third Party
from actstream import registry

# Squarelet
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.models import (
    Invitation,
    Organization,
    Plan,
    ProfileChangeRequest,
)
from squarelet.organizations.models.payment import Charge, Entitlement, EntitlementGrant
from squarelet.organizations.tasks import sync_wix_for_group_member

# Register models with django-activity-stream
registry.register(Organization)
registry.register(ProfileChangeRequest)
registry.register(Invitation)
registry.register(Entitlement)
registry.register(EntitlementGrant)

# pylint:disable=too-many-positional-arguments


def should_sync_wix(org):
    """Should we sync this org with Wix?"""
    return (
        org
        and org.share_resources
        and org.subscriptions.filter(plan__wix=True).exists()
    )


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
    for sub in parent.subscriptions.filter(plan__wix=True).select_related("plan"):
        plan_pk = sub.plan.pk
        transaction.on_commit(
            lambda c=child_pk, par=parent_pk, p=plan_pk: (
                sync_wix_for_group_member.delay(c, par, p)
            )
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
        for sub in group.subscriptions.filter(plan__wix=True).select_related("plan"):
            plan_pk = sub.plan.pk
            for member_pk in pk_set:
                transaction.on_commit(
                    lambda m=member_pk, g=group_pk, p=plan_pk: (
                        sync_wix_for_group_member.delay(m, g, p)
                    )
                )
    else:
        member_org = instance
        member_pk = member_org.pk
        for group_pk in pk_set:
            group = Organization.objects.filter(pk=group_pk).first()
            if should_sync_wix(group):
                for sub in group.subscriptions.filter(plan__wix=True).select_related(
                    "plan"
                ):
                    plan_pk = sub.plan.pk
                    transaction.on_commit(
                        lambda g=group_pk, p=plan_pk: sync_wix_for_group_member.delay(
                            member_pk, g, p
                        )
                    )


@receiver(
    signals.post_save,
    sender=Charge,
    dispatch_uid="squarelet.organizations.signals.charge_created",
)
def charge_created(sender, instance, created, **kwargs):
    """Un-hide orgs (individual or not) when a charge is created"""
    # pylint: disable=unused-argument
    if created and instance.organization.hidden:
        instance.organization.hidden = False
        instance.organization.save(update_fields=["hidden"])


# --- EntitlementGrant cache invalidation -------------------------------------
#
# Admin actions on grants (create, edit, toggle active, delete, M2M edits)
# change the set of orgs that match a grant. Each change broadcasts cache
# invalidations for the affected orgs so OIDC clients re-fetch entitlements
# immediately. The monthly `restore_organization` task handles the scheduled
# refresh cycle; these signals handle the interactive path.


def _invalidate_orgs(uuids):
    """Defer a cache-invalidation broadcast for the given org UUIDs."""
    uuid_list = list({str(u) for u in uuids})
    if not uuid_list:
        return
    transaction.on_commit(lambda: send_cache_invalidations("organization", uuid_list))


@receiver(
    signals.pre_save,
    sender=EntitlementGrant,
    dispatch_uid="squarelet.organizations.signals.entitlementgrant_stash_pre_save",
)
def entitlementgrant_stash_pre_save(sender, instance, **kwargs):
    """Stash the orgs this grant matched *before* the save.

    Needed because toggling active=False or flipping rules can shrink the
    matching set — post_save alone wouldn't see who used to match.
    """
    # pylint: disable=unused-argument,protected-access
    if instance.pk is None:
        instance._pre_save_match_uuids = []
        return
    try:
        old = EntitlementGrant.objects.get(pk=instance.pk)
    except EntitlementGrant.DoesNotExist:
        instance._pre_save_match_uuids = []
        return
    instance._pre_save_match_uuids = list(
        old.matching_organizations().values_list("uuid", flat=True)
    )


@receiver(
    signals.post_save,
    sender=EntitlementGrant,
    dispatch_uid="squarelet.organizations.signals.entitlementgrant_invalidate_on_save",
)
def entitlementgrant_invalidate_on_save(sender, instance, **kwargs):
    """Broadcast for the union of pre-save and post-save matches."""
    # pylint: disable=unused-argument
    pre = getattr(instance, "_pre_save_match_uuids", []) or []
    post = list(instance.matching_organizations().values_list("uuid", flat=True))
    _invalidate_orgs(set(pre) | set(post))


@receiver(
    signals.pre_delete,
    sender=EntitlementGrant,
    dispatch_uid="squarelet.organizations.signals.entitlementgrant_stash_pre_delete",
)
def entitlementgrant_stash_pre_delete(sender, instance, **kwargs):
    """Stash the orgs this grant matched before delete cascades the M2M."""
    # pylint: disable=unused-argument,protected-access
    instance._pre_delete_match_uuids = list(
        instance.matching_organizations().values_list("uuid", flat=True)
    )


@receiver(
    signals.post_delete,
    sender=EntitlementGrant,
    dispatch_uid=(
        "squarelet.organizations.signals.entitlementgrant_invalidate_on_delete"
    ),
)
def entitlementgrant_invalidate_on_delete(sender, instance, **kwargs):
    """Broadcast for orgs that matched immediately before the delete."""
    # pylint: disable=unused-argument
    _invalidate_orgs(getattr(instance, "_pre_delete_match_uuids", []) or [])


@receiver(
    signals.m2m_changed,
    sender=EntitlementGrant.organizations.through,
    dispatch_uid=(
        "squarelet.organizations.signals.entitlementgrant_organizations_m2m_changed"
    ),
)
def entitlementgrant_organizations_m2m_changed(
    sender, instance, action, pk_set, reverse, **kwargs
):
    """Broadcast when orgs are added to or removed from a grant's M2M."""
    # pylint: disable=unused-argument
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if reverse:
        # Reverse: instance is an Organization that just gained/lost a grant.
        _invalidate_orgs([instance.uuid])
        return
    if not pk_set:
        # v1: bare `clear()` is not handled — the admin UI uses add/remove.
        return
    uuids = list(
        Organization.objects.filter(pk__in=pk_set).values_list("uuid", flat=True)
    )
    _invalidate_orgs(uuids)


@receiver(
    signals.m2m_changed,
    sender=EntitlementGrant.entitlements.through,
    dispatch_uid=(
        "squarelet.organizations.signals.entitlementgrant_entitlements_m2m_changed"
    ),
)
def entitlementgrant_entitlements_m2m_changed(
    sender, instance, action, reverse, **kwargs
):
    """Broadcast for currently-matching orgs when a grant's entitlements change."""
    # pylint: disable=unused-argument
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if reverse:
        return  # v1: skip reverse path
    uuids = list(instance.matching_organizations().values_list("uuid", flat=True))
    _invalidate_orgs(uuids)
