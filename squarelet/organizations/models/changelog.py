# Django
from django.db import models
from django.utils.translation import gettext_lazy as _

# Squarelet
from squarelet.core.fields import AutoCreatedField
from squarelet.organizations.choices import ChangeLogReason


class OrganizationChangeLog(models.Model):
    """Track important changes to organizations"""

    created_at = AutoCreatedField(
        _("created at"), help_text=_("When the organization was changed")
    )

    organization = models.ForeignKey(
        verbose_name=_("organization"),
        to="organizations.Organization",
        on_delete=models.CASCADE,
        related_name="change_logs",
        help_text=_("The organization which changed"),
    )
    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        related_name="change_logs",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text=_("The user who changed the organization"),
    )
    reason = models.PositiveSmallIntegerField(
        _("reason"),
        choices=ChangeLogReason.choices,
        help_text=_("Which category of change occurred"),
    )

    from_plan = models.ForeignKey(
        verbose_name=_("from plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan before the change occurred"),
    )
    from_next_plan = models.ForeignKey(
        verbose_name=_("from next plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's next_plan before the change occurred"),
    )
    from_max_users = models.IntegerField(
        _("maximum users"),
        blank=True,
        null=True,
        help_text=_("The organization's max_users before the change occurred"),
    )

    to_plan = models.ForeignKey(
        verbose_name=_("to plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan after the change occurred"),
    )
    to_next_plan = models.ForeignKey(
        verbose_name=_("to next plan"),
        to="organizations.Plan",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=_("The organization's plan after the change occurred"),
    )
    to_max_users = models.IntegerField(
        _("maximum users"),
        help_text=_("The organization's max_users after the change occurred"),
    )
    credit_card = models.CharField(
        _("credit card"),
        max_length=255,
        default="",
        help_text=_("The updated credit card number"),
    )

    def describe(self):
        """A description of the change for digest emails"""
        if self.reason == ChangeLogReason.created:
            return (
                f"Created: {self.organization.name} - "
                f"Plan: {self.to_plan} with {self.to_max_users} users"
            )
        elif self.reason == ChangeLogReason.updated:
            return (
                f"Updated: {self.organization.name} - "
                f"From: Plan {self.from_plan} with {self.from_max_users} users - "
                f"To: Plan {self.to_plan} with {self.to_max_users} users"
            )
        elif self.reason == ChangeLogReason.failed:
            return (
                f"Payment Failed: {self.organization.name} - "
                f"Plan: {self.from_plan} with {self.from_max_users} users"
            )
        return "Other reason"
