# Standard Library
from datetime import date

# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.core.utils import format_stripe_error
from squarelet.organizations.models import Charge, Membership, Organization
from squarelet.organizations.models.payment import EntitlementGrant
from squarelet.organizations.payments.base import PaymentActionRequired


def _default_update_on():
    """First day of next month — the refresh date for grant-only organizations."""
    today = date.today()
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    merged = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    subtypes = serializers.StringRelatedField(many=True)
    admins = serializers.SerializerMethodField()

    parent = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    share_resources = serializers.BooleanField(read_only=True)

    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "max_users",
            "avatar_url",
            "individual",
            "private",
            "verified_journalist",
            "payment_failed",
            "updated_at",
            "merged",
            "subtypes",
            "admins",
            "parent",
            "groups",
            "share_resources",
        )

    def get_admins(self, obj):
        return [
            {
                "id": user.pk,
                "name": user.get_full_name() or user.username,
                "email": user.email,
            }
            for user in obj.users.all()
            if any(
                m.admin and m.organization_id == obj.pk for m in user.memberships.all()
            )
        ]

    def get_parent(self, obj):
        if obj.parent is not None:
            return OrganizationDetailSerializer(obj.parent, context=self.context).data
        else:
            return None

    def get_groups(self, obj):
        return OrganizationDetailSerializer(
            obj.groups.all(), many=True, context=self.context
        ).data


class OrganizationDetailSerializer(OrganizationSerializer):
    update_on = serializers.SerializerMethodField()
    entitlements = serializers.SerializerMethodField()
    card = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = OrganizationSerializer.Meta.fields + (
            "entitlements",
            "card",
            "update_on",
        )

    def get_update_on(self, obj):
        return obj.update_on or _default_update_on()

    def get_entitlements(self, obj):
        # Get the client first
        client = self.context.get("client")
        if not client:
            request = self.context.get("request")
            if request and hasattr(request, "auth") and request.auth:
                client = request.auth.client
        # If we can't find a client, then no entitlements.
        if not client:
            return []

        update_on = obj.update_on or _default_update_on()
        result = []

        # Plan-based: one entry per subscription's entitlements (no dedup)
        for sub in obj.subscriptions.prefetch_related("plan__entitlements").all():
            for ent in sub.plan.entitlements.filter(client=client):
                result.append(
                    {
                        "name": ent.name,
                        "slug": ent.slug,
                        "description": ent.description,
                        "resources": ent.resources,
                        "update_on": update_on,
                    }
                )

        # Grant-based: deduplicated by entitlement pk
        matching_grants = EntitlementGrant.objects.for_org(obj).prefetch_related(
            "entitlements"
        )
        grant_ent_pks_seen = set()
        for grant in matching_grants:
            for ent in grant.entitlements.filter(client=client):
                if ent.pk not in grant_ent_pks_seen:
                    grant_ent_pks_seen.add(ent.pk)
                    result.append(
                        {
                            "name": ent.name,
                            "slug": ent.slug,
                            "description": ent.description,
                            "resources": ent.resources,
                            "update_on": update_on,
                        }
                    )
        return result

    def get_card(self, obj):
        # this can be slow - goes to stripe for customer/card info - cache this
        return obj.customer().card_display


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationDetailSerializer()

    class Meta:
        model = Membership
        fields = ("organization", "admin")

    def to_representation(self, instance):
        """Move fields from organization to membership representation."""
        # https://stackoverflow.com/questions/21381700/django-rest-framework-how-do-you-flatten-nested-data
        representation = super().to_representation(instance)
        organization_representation = representation.pop("organization")
        for key in organization_representation:
            representation[key] = organization_representation[key]

        return representation


class StripeError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Stripe error"


class PaymentActionRequiredError(APIException):
    """HTTP 402 raised when a charge requires client-side 3DS/SCA confirmation."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "Payment action required"

    def __init__(self, exc):
        super().__init__(self.default_detail)
        self.detail = {
            "client_secret": exc.client_secret,
            "payment_intent_id": exc.payment_intent_id,
        }


class ChargeSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True, required=False)
    save_card = serializers.BooleanField(write_only=True, required=False)
    payment_intent_id = serializers.CharField(write_only=True, required=False)
    organization = serializers.SlugRelatedField(
        slug_field="uuid", queryset=Organization.objects.all()
    )

    class Meta:
        model = Charge
        fields = (
            "amount",
            "charge_id",
            "created_at",
            "description",
            "fee_amount",
            "organization",
            "payment_intent_id",
            "save_card",
            "token",
            "metadata",
        )
        read_only_fields = ("created_at", "charge_id")
        extra_kwargs = {"metadata": {"required": False}}

    def create(self, validated_data):
        """Create the charge object locally and on stripe.

        Two code paths:
        - Normal: call organization.charge(); may raise PaymentActionRequired if
          3DS is needed, which returns HTTP 402 with client_secret/payment_intent_id.
        - Confirm: called after client-side confirmCardPayment() with payment_intent_id;
          retrieves the succeeded PaymentIntent and creates the local Charge record.
        """
        organization = validated_data["organization"]
        request = self.context.get("request")
        user = request.user if request else None
        payment_intent_id = validated_data.get("payment_intent_id")
        try:
            if payment_intent_id:
                charge = Charge.objects.confirm_payment_intent(
                    payment_intent_id=payment_intent_id,
                    organization=organization,
                    amount=validated_data["amount"],
                    fee_amount=validated_data.get("fee_amount", 0),
                    description=validated_data["description"],
                    metadata=validated_data.get("metadata") or {},
                    save_card=bool(validated_data.get("save_card")),
                )
            else:
                charge = organization.charge(
                    validated_data["amount"],
                    validated_data["description"],
                    user,
                    validated_data.get("fee_amount", 0),
                    validated_data.get("token"),
                    validated_data.get("save_card"),
                    validated_data.get("metadata"),
                )
        except PaymentActionRequired as exc:
            raise PaymentActionRequiredError(exc)
        except stripe.StripeError as exc:
            user_message = format_stripe_error(exc)
            raise StripeError(user_message)
        # add the card display to the response, so the client has immediate access
        # to the newly saved card
        data = {"card": organization.customer().card_display}
        data.update(self.data)
        self._data = data
        return charge

    def validate(self, attrs):
        """Must supply token if saving card (unless confirming a payment intent)."""
        if (
            attrs.get("save_card")
            and not attrs.get("token")
            and not attrs.get("payment_intent_id")
        ):
            raise serializers.ValidationError(
                "Must supply a token if save card is true"
            )
        return attrs
