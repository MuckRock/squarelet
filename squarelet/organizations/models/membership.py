# Django
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

# Squarelet
from squarelet.core.fields import AutoCreatedField
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.querysets import MembershipQuerySet


class Membership(models.Model):
    """Through table for organization membership"""

    objects = MembershipQuerySet.as_manager()

    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    admin = models.BooleanField(
        _("admin"),
        default=False,
        help_text=_("This user has administrative rights for this organization"),
    )

    created_at = AutoCreatedField(
        _("created_at"),
        null=True,
        blank=True,
        help_text=_("When this organization was created"),
    )

    class Meta:
        unique_together = ("user", "organization")
        ordering = ("user_id",)

    def __str__(self):
        return f"Membership: {self.user} in {self.organization}"

    def save(self, *args, **kwargs):
        # Prevents circular import
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.tasks import sync_wix

        is_new = self.pk is None
        is_wix = self.organization.plan and self.organization.plan.wix

        with transaction.atomic():
            super().save(*args, **kwargs)

            # Trigger cache invalidation message to OIDC applications
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user.uuid)
            )

            # Trigger Wix sync if this is a new membership and org has a Wix plan
            if is_new and is_wix:
                transaction.on_commit(
                    lambda: sync_wix.delay(
                        self.organization.pk,
                        self.organization.plan.pk,
                        self.user.pk,
                    )
                )

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(
                lambda: send_cache_invalidations("user", self.user.uuid)
            )
            # TODO: We need to remove somebody's Wix membership here too
