# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.organizations.models import (
    Charge,
    Entitlement,
    Invitation,
    Membership,
    Organization,
    Plan,
)


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    # XXX remove plan
    plan = serializers.CharField(source="plan.slug")
    entitlements = serializers.SerializerMethodField()
    # this can be slow - goes to stripe for customer/card info - cache this
    card = serializers.CharField(source="card_display")

    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "card",
            "max_users",
            "individual",
            "private",
            "update_on",
            "updated_at",
            "payment_failed",
            "avatar_url",
        )

    def get_entitlements(self, obj):
        request = self.context.get("request")
        if request and hasattr(request, "auth") and request.auth:
            return Entitlement.objects.filter(
                plans__organization=obj, client=request.auth.client
            ).values_list("slug", flat=True)
        return []


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer()

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


class ChargeSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True, required=False)
    save_card = serializers.BooleanField(write_only=True, required=False)
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
            "save_card",
            "token",
        )
        read_only_fields = ("created_at", "charge_id")

    def create(self, validated_data):
        """Create the charge object locally and on stripe"""
        organization = validated_data["organization"]
        try:
            charge = organization.charge(
                validated_data["amount"],
                validated_data["description"],
                validated_data.get("fee_amount", 0),
                validated_data.get("token"),
                validated_data.get("save_card"),
            )
        except stripe.error.StripeError as exc:
            raise StripeError(exc.user_message)
        # add the card display to the response, so the client has immediate access
        # to the newly saved card
        data = {"card": organization.card_display}
        data.update(self.data)
        self._data = data
        return charge

    def validate(self, attrs):
        """Must supply token if saving card"""
        if attrs.get("save_card") and not attrs.get("token"):
            raise serializers.ValidationError(
                "Must supply a token if save card is true"
            )
        return attrs


# PressPass


class PressPassOrganizationSerializer(serializers.ModelSerializer):
    plan = serializers.CharField(source="plan.slug")

    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "max_users",
            "individual",
            "private",
            "update_on",
            "updated_at",
            "payment_failed",
            "avatar",
        )


class PressPassMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ("user", "admin")
        extra_kwargs = {"user": {"read_only": True}}


class PressPassNestedInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = (
            "organization",
            "email",
            "user",
            "request",
            "created_at",
            "accepted_at",
            "rejected_at",
        )
        extra_kwargs = {
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
            "rejected_at": {"read_only": True},
        }


class PressPassInvitationSerializer(serializers.ModelSerializer):
    accept = serializers.BooleanField(write_only=True)
    reject = serializers.BooleanField(write_only=True)

    class Meta:
        model = Invitation
        fields = (
            "organization",
            "email",
            "user",
            "request",
            "created_at",
            "accepted_at",
            "rejected_at",
            "accept",
            "reject",
        )
        extra_kwargs = {
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
            "rejected_at": {"read_only": True},
            "organization": {"read_only": True},
            "email": {"read_only": True},
            "user": {"read_only": True},
        }

    def validate(self, attrs):
        """Must not try to accept and reject"""
        if attrs.get("accept") and attrs.get("reject"):
            raise serializers.ValidationError(
                "May not accept and reject the invitation"
            )
        return attrs


class PressPassPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "name",
            "slug",
            "minimum_users",
            "base_price",
            "price_per_user",
            "feature_level",
            "public",
            "annual",
            "for_individuals",
            "for_groups",
            "requires_updates",
        )
        extra_kwargs = {"slug": {"read_only": True}}
