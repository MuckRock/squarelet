# Django
from django.db import models
from django.db.models import Q
from django.utils.timezone import get_current_timezone

# Standard Library
from datetime import datetime

# Third Party
import stripe


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

    def create_individual(self, user):
        """Create an individual organization for user
        The user model must be unsaved
        """
        # pylint: disable=cyclic-import
        from squarelet.organizations.models import Plan
        from squarelet.organizations.models import OrganizationChangeLog

        free_plan = Plan.objects.get(slug="free")
        user.individual_organization = self.create(
            name=user.username,
            individual=True,
            private=True,
            max_users=1,
            plan=free_plan,
            next_plan=free_plan,
        )
        user.save()
        user.individual_organization.add_creator(user)
        user.individual_organization.change_logs.create(
            reason=OrganizationChangeLog.CREATED,
            user=user,
            to_plan=user.individual_organization.plan,
            to_next_plan=user.individual_organization.next_plan,
            to_max_users=user.individual_organization.max_users,
        )
        return user.individual_organization


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


class ChargeQuerySet(models.QuerySet):
    def make_charge(self, organization, token, amount, fee_amount, description):
        """Make a charge on stripe and locally"""
        customer = organization.customer
        if token:
            source = customer.sources.create(source=token)
        else:
            source = organization.card

        stripe_charge = stripe.Charge.create(
            amount=amount,
            currency="usd",
            customer=customer,
            description=description,
            source=source,
            metadata={
                "organization": organization.name,
                "organization id": organization.uuid,
                "fee amount": fee_amount,
            },
        )
        if token:
            source.delete()

        # use get or create as there is a race condition from creating the charge on
        # stripe, to receiving the webhook and saving it to the database there,
        # and saving it here
        charge, _ = self.get_or_create(
            charge_id=stripe_charge.id,
            defaults={
                "amount": amount,
                "fee_amount": fee_amount,
                "organization": organization,
                "created_at": datetime.fromtimestamp(
                    stripe_charge.created, tz=get_current_timezone()
                ),
                "description": description,
            },
        )
        return charge
