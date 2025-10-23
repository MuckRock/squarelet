# Django
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import Q
from django.utils.timezone import get_current_timezone

# Standard Library
from datetime import date, datetime
from uuid import uuid4

# Third Party
import stripe
from dateutil.relativedelta import relativedelta

# Squarelet
from squarelet.organizations.choices import ChangeLogReason

stripe.api_version = "2018-09-24"
stripe.api_key = settings.STRIPE_SECRET_KEY


class OrganizationQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            # staff can always view all organizations
            return self
        elif user.is_authenticated:
            # other users may not see private organizations unless they are a member
            # and they can only see public organizations that are visible
            # (verified or have charges)
            return self.filter(
                Q(private=False, verified_journalist=True)
                | Q(private=False, charges__isnull=False)
                | Q(users=user)
            ).distinct()
        else:
            # anonymous users may only see public organizations that are visible
            return self.filter(
                Q(private=False, verified_journalist=True)
                | Q(private=False, charges__isnull=False)
            ).distinct()

    def create_individual(self, user, uuid=None):
        """Create an individual organization for user
        The user model must be unsaved
        """
        kwargs = {}
        if uuid is not None:
            kwargs["uuid"] = uuid
        user.individual_organization = self.create(
            name=user.username, individual=True, private=True, max_users=1, **kwargs
        )
        user.save()
        user.individual_organization.add_creator(user)
        user.individual_organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=user,
            to_plan=user.individual_organization.plan,
            to_max_users=user.individual_organization.max_users,
        )
        return user.individual_organization


class MembershipQuerySet(models.QuerySet):
    def get_viewable(self, user):
        """Returns memberships in public orgs or any org the user is a member of"""
        # you can view membership info if:
        #  * this organization is public, regardless of your membership
        #  * or, you are a member of the org
        return self.filter(Q(organization__private=False) | Q(organization__users=user))


class PlanQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            return self
        elif user.is_authenticated:
            return self.filter(
                Q(public=True)
                | Q(organizations__in=user.organizations.all())
                | Q(private_organizations__in=user.organizations.all())
            ).distinct()
        else:
            return self.filter(public=True)

    def get_public(self):
        return self.get_viewable(AnonymousUser())

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


class EntitlementQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            return self
        elif user.is_authenticated:
            return self.filter(Q(plans__public=True) | Q(client__owner=user)).distinct()
        else:
            return self.filter(plans__public=True)

    def get_public(self):
        return self.get_viewable(AnonymousUser())

    def get_subscribed(self, user):
        if user.is_authenticated:
            return self.filter(
                plans__organizations__in=user.organizations.all()
            ).distinct()
        else:
            return self.none()

    def get_owned(self, user):
        if user.is_authenticated:
            return self.filter(client__owner=user)
        else:
            return self.none()


class InvitationQuerySet(models.QuerySet):
    def get_open(self):
        return self.filter(accepted_at=None, rejected_at=None)

    def get_pending(self):
        return self.get_open().filter()

    def get_pending_invitations(self):
        return self.get_open().filter(request=False)

    def get_pending_requests(self):
        return self.get_open().filter(request=True)

    def get_accepted(self):
        return self.exclude(accepted_at=None)

    def get_rejected(self):
        return self.exclude(rejected_at=None)


class ChargeQuerySet(models.QuerySet):
    def make_charge(
        self,
        organization,
        token,
        amount,
        fee_amount,
        description,
        metadata,
    ):
        """Make a charge on stripe and locally"""
        customer = organization.customer()
        if token:
            source = customer.add_source(token)
        else:
            source = customer.card

        default_metadata = {
            "organization": organization.name,
            "organization id": str(organization.uuid),
            "fee amount": fee_amount,
            **metadata,
        }

        stripe_charge = stripe.Charge.create(
            amount=amount,
            currency="usd",
            customer=customer.stripe_customer,
            description=description,
            source=source,
            metadata=default_metadata,
            statement_descriptor_suffix=metadata.get("action", ""),
            idempotency_key=str(uuid4()),
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
                "metadata": default_metadata,
            },
        )
        return charge


class SubscriptionQuerySet(models.QuerySet):
    def start(self, organization, plan, payment_method="card"):
        subscription = self.model(
            organization=organization,
            plan=plan,
            update_on=date.today() + relativedelta(months=1),
        )
        subscription.start(payment_method=payment_method)
        subscription.save()
        return subscription

    def sunlight_active_count(self):
        """Count active Sunlight subscriptions across all variants"""
        return self.filter(
            plan__slug__startswith="sunlight-",
            plan__wix=True,
            cancelled=False,
        ).count()
