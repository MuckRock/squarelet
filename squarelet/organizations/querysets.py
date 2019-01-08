# Django
from django.db import models
from django.db.models import Q


class OrganizationQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            # staff can always view all organizations
            return self
        elif user.is_authenticated:
            # other users may not see private organizations unless they are a member
            return self.filter(Q(private=False) | Q(users=user)).distinct()
        else:
            # anonymous users may not see any private organizations
            return self.filter(private=False)


class PlanQuerySet(models.QuerySet):
    def individual_choices(self):
        return self.filter(public=True, for_individuals=True)

    def group_choices(self):
        return self.filter(public=True, for_groups=True)


class InvitationQuerySet(models.QuerySet):
    def get_pending(self):
        return self.filter(accepted_at=None, request=False)

    def get_accepted(self):
        return self.exclude(accepted_at=None)

    def get_requested(self):
        return self.filter(accepted_at=None, request=True)
