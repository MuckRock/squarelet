# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Local
from .models import Charge, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False, source="id")
    plan = serializers.CharField(source="plan.slug")
    # XXX this can be slow - goes to stripe for customer/card info
    # may create customer
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

    class Meta:
        model = Charge
        fields = (
            "amount",
            "organization",
            "created_at",
            "charge_id",
            "description",
            "token",
            "save_card",
        )
        read_only_fields = ("created_at", "charge_id")

    def create(self, validated_data):
        """Create the charge object locally and on stripe"""
        organization = validated_data["organization"]
        try:
            charge = organization.charge(
                validated_data["amount"],
                validated_data["description"],
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
