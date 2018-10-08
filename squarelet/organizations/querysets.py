
# Django
from django.db import models
from django.db.models import Q


class OrganizationQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            # staff can always view all organizations
            return self
        else:
            # other users may not see privat eorganizations unless they are a member
            return self.filter(Q(private=False) | Q(organizationmembership__user=user))
