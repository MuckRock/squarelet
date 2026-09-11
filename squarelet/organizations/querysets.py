# Django
from django.contrib.auth.models import AnonymousUser
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import get_current_timezone

# Standard Library
from datetime import datetime, timedelta
from uuid import uuid4

# Third Party
from fuzzywuzzy import fuzz, process

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.payments.factory import get_payment_provider

# pylint:disable=too-many-positional-arguments


class OrganizationQuerySet(models.QuerySet):
    def get_viewable(self, user):
        if user.is_staff:
            # staff can always view all organizations
            return self

        qs = self
        if user.is_authenticated:
            # other users may not see private organizations unless they are a member
            # or they can auto join that org
            # and they can only see public organizations that are visible
            # (verified or have charges or paid invoices)
            auto_join_org_pks = user.get_potential_organizations().values("pk")
            viewable_filter = (
                Q(private=False, verified_journalist=True)
                | Q(private=False, charges__isnull=False)
                | Q(private=False, invoices__status="paid")
                | Q(users=user)
                | Q(pk__in=auto_join_org_pks)
            )
            return qs.filter(viewable_filter).distinct()
        else:
            return qs.filter(
                Q(private=False, verified_journalist=True)
                | Q(private=False, charges__isnull=False)
                | Q(private=False, invoices__status="paid")
            ).distinct()

    def fuzzy_search(self, name, limit=10, score_cutoff=83):
        """Fuzzy search for non-individual organizations by name"""
        group_orgs = dict(
            self.filter(individual=False)
            .values_list("pk", "name")
            .iterator(chunk_size=200)
        )
        matching_orgs = process.extractBests(
            name,
            group_orgs,
            limit=limit,
            scorer=fuzz.partial_ratio,
            score_cutoff=score_cutoff,
        )
        matched_pks = [pk for _, _, pk in matching_orgs]
        if not matched_pks:
            return self.none()
        # Preserve match order using CASE/WHEN
        preserved = models.Case(
            *[models.When(pk=pk, then=pos) for pos, pk in enumerate(matched_pks)]
        )
        return self.filter(pk__in=matched_pks).order_by(preserved)

    def create_individual(self, user, uuid=None):
        """Create an individual organization for user
        The user model must be unsaved
        """
        kwargs = {}
        if uuid is not None:
            kwargs["uuid"] = uuid
        user.individual_organization = self.create(
            name=user.username, individual=True, private=False, max_users=1, **kwargs
        )
        user.save()
        user.individual_organization.add_creator(user)
        user.individual_organization.change_logs.create(
            reason=ChangeLogReason.created,
            user=user,
            to_plan=user.individual_organization.get_plans().first(),
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
                | Q(subscriptions__organization__in=user.organizations.all())
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
            | Q(subscriptions__organization=organization)
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
                plans__subscriptions__organization__in=user.organizations.all()
            ).distinct()
        else:
            return self.none()

    def get_owned(self, user):
        if user.is_authenticated:
            return self.filter(client__owner=user)
        else:
            return self.none()

    def for_organization(self, org, client=None):
        """Return the deduped union of plan-derived and grant-derived entitlements
        currently available to `org`. Optionally scoped to a single OIDC client."""
        # Lazy import to avoid a circular import (payment.py imports this module)
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.models.payment import EntitlementGrant

        matching_grants = EntitlementGrant.objects.for_org(org)
        qs = self.filter(
            Q(plans__subscriptions__organization=org) | Q(grants__in=matching_grants)
        )
        if client is not None:
            qs = qs.filter(client=client)
        return qs.distinct()


class EntitlementGrantQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)

    def for_org(self, org):
        """Active grants that apply to `org`.

        A grant matches when the org type is compatible AND either:
        - the org is explicitly listed in `organizations`, OR
        - the grant has at least one rule flag set and every active rule is
          satisfied by this org's attributes.
        """
        org_type_q = Q(for_individuals=True) if org.individual else Q(for_groups=True)
        explicit_q = org_type_q & Q(organizations=org)

        at_least_one_rule = Q(require_verified=True) | Q(
            require_active_subscription=True
        )
        # If the org fails a requirement, exclude grants that set that flag.
        verified_ok = Q() if org.verified_journalist else Q(require_verified=False)
        sub_ok = (
            Q()
            if org.has_active_subscription()
            else Q(require_active_subscription=False)
        )
        rule_q = org_type_q & at_least_one_rule & verified_ok & sub_ok

        return self.active().filter(explicit_q | rule_q).distinct()


class InvitationQuerySet(models.QuerySet):
    def get_open(self):
        return self.filter(accepted_at=None, rejected_at=None, withdrawn_at=None)

    def get_withdrawn(self):
        return self.exclude(withdrawn_at=None)

    def get_pending(self):
        return self.get_open().filter()

    def get_pending_invitations(self):
        return self.get_open().filter(request=False)

    def get_pending_requests(self):
        return self.get_open().filter(request=True)

    def get_rejected_requests(self):
        return self.filter(request=True, rejected_at__isnull=False)

    def get_accepted(self):
        return self.exclude(accepted_at=None)

    def get_rejected(self):
        return self.exclude(rejected_at=None)

    def for_user(self, user):
        """Filter invitations/requests for a user's emails or user field

        Matches against all of the user's email addresses (verified or not) so
        that users who haven't confirmed their email can still see their
        invitations.  Accepting an admin-role invitation is separately gated
        behind email verification (see
        InvitationAcceptForm.requires_email_verification).
        """
        emails = user.get_emails()
        return self.filter(Q(email__in=emails) | Q(user=user))

    def get_user_invitations(self, user):
        """Get all invitations (request=False) for a user"""
        return (
            self.for_user(user)
            .filter(request=False)
            .select_related("organization")
            .order_by("-created_at")
        )

    def get_user_requests(self, user):
        """Get all requests (request=True) for a user"""
        return (
            self.for_user(user)
            .filter(request=True)
            .select_related("organization")
            .order_by("-created_at")
        )

    def get_org_invitations(self, organization):
        """Get all invitations (request=False) sent by an organization"""
        return (
            self.filter(organization=organization, request=False)
            .select_related("user")
            .order_by("-created_at")
        )

    def get_org_requests(self, organization):
        """Get all requests (request=True) received by an organization"""
        return (
            self.filter(organization=organization, request=True)
            .select_related("user")
            .order_by("-created_at")
        )


class OrganizationInvitationQuerySet(models.QuerySet):
    def pending(self):
        """Return pending invitations (neither accepted, rejected, nor withdrawn)"""
        return self.filter(accepted_at=None, rejected_at=None, withdrawn_at=None)

    def withdrawn(self):
        """Return withdrawn invitations"""
        return self.exclude(withdrawn_at=None)

    def accepted(self):
        """Return accepted invitations"""
        return self.exclude(accepted_at=None)

    def rejected(self):
        """Return rejected invitations"""
        return self.exclude(rejected_at=None)

    def invitations(self):
        """Return pending invitations (not requests)"""
        return self.pending().filter(request=False)

    def requests(self):
        """Return pending requests (not invitations)"""
        return self.pending().filter(request=True)

    def for_organization(self, organization):
        """Return invitations to or from the given organization"""
        return self.filter(
            Q(from_organization=organization) | Q(to_organization=organization)
        )


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
            source = customer.payment_method
            if source is None:
                raise ValueError("No payment method on file for this organization.")

        default_metadata = {
            "organization": organization.name,
            "organization id": str(organization.uuid),
            "fee amount": fee_amount,
            **metadata,
        }

        stripe_charge = (
            get_payment_provider()
            .get_charge_service()
            .create(
                amount=amount,
                currency="usd",
                customer=customer.stripe_customer,
                description=description,
                source=source,
                metadata=default_metadata,
                statement_descriptor_suffix=metadata.get("action", ""),
                idempotency_key=str(uuid4()),
            )
        )
        if token:
            get_payment_provider().get_customer_service().remove_source(source)

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

    def confirm_payment_intent(
        self,
        payment_intent_id,
        organization,
        amount,
        fee_amount,
        description,
        metadata,
        save_card=False,
    ):
        """Create a local Charge after the client completes 3DS confirmation."""
        default_metadata = {
            "organization": organization.name,
            "organization id": str(organization.uuid),
            "fee amount": fee_amount,
            **metadata,
        }
        provider = get_payment_provider()
        stripe_charge, pm_id = provider.get_charge_service().confirm_payment_intent(
            payment_intent_id
        )
        if not save_card and pm_id:
            # Detach the temporary PM that was attached for this one-time charge
            provider.get_customer_service().remove_source(pm_id)

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


class SubscriptionItemQuerySet(models.QuerySet):
    @staticmethod
    def _schedule_single_period(item):
        """A plan that bills once and stops means, for a line, exactly what a
        customer cancellation means: drop it at the end of the period it was
        paid for.  The subscription carries on for its other lines, and
        Resubscribe reverses this if they change their mind.

        Saves the cancellation pair and nothing else: `stripe_modify` has
        already recorded this line's Stripe id against a different instance,
        so a full save would write the empty value back over it."""
        item.mark_cancelled(item.subscription.current_period_end)
        item.save(update_fields=item.CANCELLATION_FIELDS)

    @staticmethod
    def _collection_method(interval, payment_method):
        """Stripe collects annual subscriptions by invoice when asked."""
        if interval == "annual" and payment_method == "invoice":
            return "send_invoice"
        return "charge_automatically"

    @staticmethod
    def resolve_purchase(plan, nonprofit=False):
        """What a new subscription to `plan` should actually be recorded as.

        Returns `(canonical_plan, plan_price)`, or `(plan, None)` when there
        is nothing to resolve to - which is every plan until
        `consolidate_stripe_products` has run, and any plan the mapping does
        not cover.  Falling back leaves the subscription on the legacy plan
        and the legacy Stripe id, which is what it would have been anyway;
        the migration picks those up.

        The plan a customer picks is not necessarily the plan they end up
        on.  Annual and nonprofit are separate `Plan` rows today, and both
        collapse onto a canonical tier where the difference is carried by
        the price's `interval` and `label` instead.  Resolving both here
        means a new subscription is recorded exactly as a migrated one is,
        so the migration has genuinely nothing to do for it.
        """
        # Lazy import to avoid a circular import (payment.py imports this module)
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.models.payment import PlanPrice
        from squarelet.organizations.plan_mapping import resolve_target

        target = resolve_target(plan.slug, allow_comped=False) or (
            plan.slug,
            "annual" if plan.annual else "monthly",
            "nonprofit" if nonprofit else "standard",
            "",
        )
        canonical_slug, interval, label, code = target

        price = (
            PlanPrice.objects.select_related("plan")
            .filter(
                plan__slug=canonical_slug,
                interval=interval,
                label=label,
                code=code,
                active=True,
            )
            .first()
        )
        if price is None:
            return plan, None
        if not price.stripe_price_id and price.amount != 0:
            # A paid price that has no Stripe Price yet - the partial state
            # `consolidate_stripe_products` leaves behind when it fails
            # part-way and completes on a re-run.
            #
            # Resolving to it anyway is worse than not resolving at all.
            # The line would be recorded against the canonical plan and take
            # its interval from the price, while `stripe_price_id` fell back
            # to the canonical plan's *legacy* row - which is the monthly
            # standard one.  An annual nonprofit would then bill the monthly
            # standard amount on a subscription recorded as annual: wrong
            # money, wrong cadence, and rejected outright by Stripe if the
            # annual subscription already carries another line.
            #
            # Staying on the picked plan bills exactly what it billed
            # before, which is the safe reading of "not ready yet".  The
            # migration picks these up like any other unresolved line.
            #
            # Keyed on the amount rather than on the blank id alone: a $0
            # price has no Stripe Price and never will, which is finished
            # rather than half-done.  (A comped one cannot reach here at
            # all - `resolve_target` refuses comped, and the unmapped
            # fallback only ever asks for standard or nonprofit.)
            return plan, None
        return price.plan, price

    @staticmethod
    def canonical_plan(plan, nonprofit=False):
        """The plan a purchase of `plan` will actually be recorded against.

        For guarding a purchase before making it.  `start` stores the
        resolved plan, not the one the customer picked, so anything asking
        "do they already hold this?" has to ask about the same row - an
        organization on `sunlight-essential` who buys the annual variant is
        not buying a different plan, and `unique_together(subscription,
        plan)` will say so with an IntegrityError if nobody asks first.
        """
        canonical, _price = SubscriptionItemQuerySet.resolve_purchase(plan, nonprofit)
        return canonical

    def start(
        self, organization, plan, payment_method="card", quantity=1, nonprofit=False
    ):
        """Add a line for `plan` and make sure Stripe knows about it.

        Stripe requires every item on a subscription to share a billing
        interval and a collection method, so those two fields decide which
        subscription the line joins.  A line that matches an existing
        subscription is added to it and bills on the same invoice; one that
        does not starts a new subscription.

        Returns the new line and the Stripe subscription carrying it, which
        is None for a subscription that costs nothing.
        """
        # Lazy import to avoid a circular import (payment.py imports this module)
        # pylint: disable=import-outside-toplevel
        # Squarelet
        from squarelet.organizations.models.payment import Subscription

        canonical_plan, plan_price = self.resolve_purchase(plan, nonprofit)
        # The billing shape follows the resolved price, not `plan.annual`.
        # Annual is a separate `Plan` row today, and the row a customer picks
        # is not always the row they end up on -- the nonprofit variants are
        # substituted in by the form.  Trusting the flag would let an annual
        # price land on a subscription recorded as monthly, which groups it
        # onto the wrong invoice and picks the wrong collection method.
        interval = (
            plan_price.interval
            if plan_price
            else "annual" if plan.annual else "monthly"
        )
        collection_method = self._collection_method(interval, payment_method)
        subscription, created = Subscription.objects.get_or_create(
            organization=organization,
            interval=interval,
            collection_method=collection_method,
        )
        # Stripe inside the transaction on purpose.  The row has to exist
        # before the call, because it is what `stripe_items` describes - but
        # a Stripe failure must not leave an organization holding a line it
        # is not being billed for.  The reverse order is the survivable one:
        # Stripe succeeding and the commit failing leaves a subscription
        # Stripe knows about and we retry into.
        with transaction.atomic():
            item = self.model.objects.create(
                subscription=subscription,
                plan=canonical_plan,
                plan_price=plan_price,
                quantity=quantity,
            )

            if subscription.cancelled and not item.is_free and plan.auto_renew:
                # They are buying a renewing plan on a subscription that is
                # ending.  Stripe ends a subscription whole, so keeping this
                # line means the subscription has to carry on - and the call
                # below sends the lifted flag in the same breath as the new
                # line.  What they cancelled still stops on its own date.
                subscription.keep_renewing_for(item)

            if created or not subscription.subscription_id:
                stripe_subscription = subscription.start(
                    payment_method=payment_method,
                    anchor_day=(
                        organization.billing_anchor.day
                        if organization.billing_anchor
                        else None
                    ),
                )
            else:
                # The subscription is already live on Stripe, so the new line
                # is pushed onto it rather than opening a second subscription.
                # Take what Stripe returned, not the cached object: that
                # was fetched before the line was added, so it does not
                # contain it.
                stripe_subscription = subscription.stripe_modify()
                if stripe_subscription is not None:
                    subscription.settle_added_line(stripe_subscription)

            # Both branches save the cancellation pair and nothing else.  A
            # full save would write this instance's fields over the row, and
            # `stripe_modify` above has already recorded `stripe_item_id`
            # against it through a *different* instance - so a plain
            # `item.save()` puts the empty value back and undoes the
            # identification the line was just given.
            if subscription.cancelled:
                # Still ending, so this line is free or a one-off - a paid
                # renewing line lifted the cancellation above.  Stripe ends
                # a subscription whole, so this one stops with the rest of
                # them whatever it says locally.  Saying so keeps the
                # billing page honest - it would otherwise advertise a
                # renewal, and offer to cancel a line that is about to
                # vanish on its own.
                item.inherit_cancellation_from(subscription)
                item.save(
                    update_fields=[
                        *item.CANCELLATION_FIELDS,
                        "cancelled_with_subscription",
                    ]
                )
            elif not plan.auto_renew:
                # Inside the transaction that creates the line, because it is
                # a fact about that line: committing one without the other
                # leaves a plan meant to bill once renewing forever, with
                # nothing to sweep it.
                self._schedule_single_period(item)

        # Every new line, as master did.  Gating this on price was a change
        # nobody asked for: `notify_started` already decides who to enrol by
        # entitlement - only the line that first grants `organization`, and
        # only once - so a free plan carrying that entitlement stopped
        # enrolling anyone, and no free signup produced a Slack notification.
        item.notify_started()
        return item, stripe_subscription

    def sunlight_active_count(self):
        """Count active Sunlight subscriptions across all variants"""
        return self.filter(
            plan__slug__startswith="sunlight-",
            plan__wix=True,
        ).count()


class InvoiceQuerySet(models.QuerySet):
    def overdue(self, grace_period_days):
        """Get invoices that are past their due date plus grace period"""
        cutoff_date = timezone.now().date() - timedelta(days=grace_period_days)
        return self.filter(status="open", due_date__lte=cutoff_date)
