# Django
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Standard Library
import uuid

# Squarelet
from squarelet.core.fields import AutoCreatedField
from squarelet.core.mail import ORG_TO_ADMINS, send_mail
from squarelet.core.utils import mailchimp_journey
from squarelet.organizations.choices import RelationshipType
from squarelet.organizations.models.membership import Membership
from squarelet.organizations.querysets import (
    InvitationQuerySet,
    OrganizationInvitationQuerySet,
)
from squarelet.organizations.tasks import sync_wix_for_group_member


class Invitation(models.Model):
    """An invitation for a user to join an organization"""

    objects = InvitationQuerySet.as_manager()

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        related_name="invitations",
        on_delete=models.CASCADE,
        help_text=_("The organization this invitation is for"),
    )
    uuid = models.UUIDField(
        _("UUID"),
        default=uuid.uuid4,
        editable=False,
        help_text=_("This UUID serves as a secret token for this invitation in URLs"),
    )
    email = models.EmailField(
        _("email"),
        blank=True,
        help_text=_("The email address to send this invitation to"),
    )
    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="invitations",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_(
            "The user this invitation is for.  Used if a user requested an "
            "invitation directly as opposed to an admin inviting them via email."
        ),
    )
    request = models.BooleanField(
        _("request"),
        help_text="Is this a request for an invitation from the user or an invitation "
        "to the user from an admin?",
        default=False,
    )
    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this invitation was created")
    )
    accepted_at = models.DateTimeField(
        _("accepted at"),
        blank=True,
        null=True,
        help_text=_(
            "When this invitation was accepted.  NULL signifies it has not been "
            "accepted yet"
        ),
    )
    rejected_at = models.DateTimeField(
        _("rejected at"),
        blank=True,
        null=True,
        help_text=_(
            "When this invitation was rejected.  NULL signifies it has not been "
            "rejected yet"
        ),
    )

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Invitation: {self.uuid}"

    def send(self):

        if self.request:
            send_mail(
                subject=_(f"{self.user} has requested to join {self.organization}"),
                template="organizations/email/join_request.html",
                organization=self.organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={"joiner": self.user},
            )
        else:
            send_mail(
                subject=_(f"Invitation to join {self.organization.name}"),
                template="organizations/email/invitation.html",
                to=[self.email],
                extra_context={"invitation": self},
            )

    @transaction.atomic
    def accept(self, user=None):
        """Accept the invitation"""
        if self.user is None and user is None:
            raise ValueError(
                "Must give a user when accepting if invitation has no user"
            )
        if self.accepted_at or self.rejected_at:
            raise ValueError("This invitation has already been closed")
        if self.user is None:
            self.user = user
        self.accepted_at = timezone.now()
        self.save()
        if (
            self.organization.verified_journalist
            and not self.user.verified_journalist()
        ):
            mailchimp_journey(self.user.email, "verified")
        if not self.organization.has_member(self.user):
            # Wix sync will be triggered automatically when Membership saves
            Membership.objects.create(organization=self.organization, user=self.user)

    def reject(self):
        """Reject or revoke the invitation"""
        if self.accepted_at or self.rejected_at:
            raise ValueError("This invitation has already been closed")
        self.rejected_at = timezone.now()
        self.save()

    def get_name(self):
        """Returns the name or email if no name is set"""
        if self.user is not None and self.user.name:
            return f"{self.user.name} ({self.email})"
        else:
            return self.email


class OrganizationInvitation(models.Model):
    """
    Invitation for an organization to join another organization
    as a member (in a membership group) or child (in a parent-child hierarchy).

    Can be either:
    - An invitation: group/parent invites an org to join
    - A request: org requests to join a group
    """

    objects = OrganizationInvitationQuerySet.as_manager()

    uuid = models.UUIDField(
        _("UUID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("UUID serves as secret token for this invitation in URLs"),
    )

    from_organization = models.ForeignKey(
        verbose_name=_("from organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="outgoing_org_invitations",
        help_text=_(
            "The organization extending the invitation or receiving the request.  "
            "This is always the organization that is the parent or group."
        ),
    )

    to_organization = models.ForeignKey(
        verbose_name=_("to organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="incoming_org_invitations",
        help_text=_(
            "The organization being invited.  This is always the child or member"
        ),
    )

    from_user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="+",
        on_delete=models.PROTECT,
        help_text=_("The user who initiated this invitation"),
    )
    closed_by_user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="+",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_("The user who accepted or rejected this invitation"),
    )

    relationship_type = models.PositiveSmallIntegerField(
        _("relationship type"),
        choices=RelationshipType.choices,
        help_text=_("Type of relationship: member or child"),
    )

    request = models.BooleanField(
        _("request"),
        default=False,
        help_text=_(
            "True if this is a request TO JOIN from to_organization. "
            "False if this is an invitation FROM from_organization."
        ),
    )

    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this invitation was created")
    )

    accepted_at = models.DateTimeField(
        _("accepted at"),
        blank=True,
        null=True,
        help_text=_("When accepted (NULL if pending)"),
    )

    rejected_at = models.DateTimeField(
        _("rejected at"),
        blank=True,
        null=True,
        help_text=_("When rejected (NULL if pending)"),
    )

    message = models.TextField(
        _("message"),
        blank=True,
        help_text=_("Optional message from the inviter"),
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        direction = "Request from" if self.request else "Invitation to"
        return f"{direction} {self.to_organization} by {self.from_organization}"

    def clean(self):
        """Validate invitation requirements"""

        if self.accepted_at and self.rejected_at:
            raise ValidationError("Cannot be both accepted and rejected")

        # Verify from org has collective enabled
        if self.from_organization and not self.from_organization.collective_enabled:
            raise ValidationError(
                f"{self.from_organization.name} does "
                "not have collective feature enabled"
            )

    @property
    def is_pending(self):
        """Is this invitation still pending (not accepted or rejected)?"""
        return self.accepted_at is None and self.rejected_at is None

    @property
    def is_accepted(self):
        """Has this invitation been accepted?"""
        return self.accepted_at is not None

    @property
    def is_rejected(self):
        """Has this invitation been rejected?"""
        return self.rejected_at is not None

    def send(self):
        """Send email notification for this invitation/request"""
        if self.request:
            # This is a request TO JOIN - notify group admins
            send_mail(
                subject=_(
                    f"{self.to_organization} has requested to join "
                    f"{self.from_organization}"
                ),
                template="organizations/email/org_join_request.html",
                organization=self.from_organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={
                    "invitation": self,
                    "requesting_org": self.to_organization,
                },
            )
        else:
            # This is an invitation TO the org - notify target org admins
            send_mail(
                subject=_(f"Invitation to join {self.from_organization.name}"),
                template="organizations/email/org_invitation.html",
                organization=self.to_organization,
                organization_to=ORG_TO_ADMINS,
                extra_context={"invitation": self},
            )

    @transaction.atomic
    def accept(self):
        """Accept this invitation/request"""
        if not self.is_pending:
            raise ValueError("This invitation has already been processed")

        self.accepted_at = timezone.now()
        self.save()

        # Create the relationship based on type
        if self.relationship_type == RelationshipType.member:
            # Add to membership group (simple M2M)
            self.from_organization.members.add(self.to_organization)
        elif self.relationship_type == RelationshipType.child:
            # Set parent relationship
            self.to_organization.parent = self.from_organization
            self.to_organization.save()

        # Trigger Wix sync if the group has a Wix plan and shares resources
        group = self.from_organization
        if group.share_resources and group.plan and group.plan.wix:
            to_org_pk = self.to_organization.pk
            group_pk = group.pk
            plan_pk = group.plan.pk
            transaction.on_commit(
                lambda: sync_wix_for_group_member.delay(to_org_pk, group_pk, plan_pk)
            )

    @transaction.atomic
    def reject(self):
        """Reject this invitation/request"""

        if not self.is_pending:
            raise ValueError("This invitation has already been processed")

        self.rejected_at = timezone.now()
        self.save()
