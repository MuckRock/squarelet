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
    def choices(self, organization):
        """Return the plan choices for the given organization"""
        if organization.individual:
            queryset = self.filter(for_individuals=True)
        else:
            queryset = self.filter(for_groups=True)
        # show public plans, the organizations current plan, and any custom plan
        # to which they have been granted explicit access
        return queryset.filter(
            Q(public=True)
            | Q(organizations=organization)
            | Q(private_organizations=organization)
        ).distinct()

    def free(self):
        """Free plans"""
        return self.filter(base_price=0, price_per_user=0)


class InvitationQuerySet(models.QuerySet):
    def get_open(self):
        return self.filter(accepted_at=None, rejected_at=None)

    def get_pending(self):
        return self.get_open().filter(request=False)

    def get_requested(self):
        return self.get_open().filter(request=True)

    def get_accepted(self):
        return self.exclude(accepted_at=None)

    def get_rejected(self):
        return self.exclude(rejected_at=None)
