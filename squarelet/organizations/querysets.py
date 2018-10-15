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
            return self.filter(Q(private=False) | Q(memberships__user=user))
        else:
            # anonymous users may not see any private organizations
            return self.filter(private=False)
