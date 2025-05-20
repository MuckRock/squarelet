# Django
from django.db.models.expressions import F

# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.organizations.models import Charge, Invitation, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    # remove plan once all clients are updated to handle entitlements
    plan = serializers.SerializerMethodField()
    # remove update_on once all clients are updated to handle entitlements
    update_on = serializers.SerializerMethodField()
    entitlements = serializers.SerializerMethodField()
    card = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "entitlements",
            "card",
            "max_users",
            "individual",
            "private",
            "verified_journalist",
            "updated_at",
            "payment_failed",
            "avatar_url",
            "update_on",
        )

    def get_plan(self, obj):
        return obj.plan.slug if obj.plan else "free"

    def get_update_on(self, _obj):
        return None

    def get_entitlements(self, obj):
        client = self.context.get("client")
        if not client:
            request = self.context.get("request")
            if request and hasattr(request, "auth") and request.auth:
                client = request.auth.client

        if client:
            return list(
                client.entitlements.filter(plans__organizations=obj)
                .annotate(update_on=F("plans__subscriptions__update_on"))
                .values("name", "slug", "description", "resources", "update_on")
            )
        return []

    def get_card(self, obj):
        # this can be slow - goes to stripe for customer/card info - cache this
        return obj.customer().card_display


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
            "metadata",
        )
        read_only_fields = ("created_at", "charge_id")
        extra_kwargs = {"metadata": {"required": False}}

    def create(self, validated_data):
        """Create the charge object locally and on stripe"""
        organization = validated_data["organization"]
        request = self.context.get("request")
        if request:
            user = request.user
        else:
            user = None
        try:
            charge = organization.charge(
                validated_data["amount"],
                validated_data["description"],
                user,
                validated_data.get("fee_amount", 0),
                validated_data.get("token"),
                validated_data.get("save_card"),
                validated_data.get("metadata"),
            )
        except stripe.error.StripeError as exc:
            raise StripeError(exc.user_message)
        # add the card display to the response, so the client has immediate access
        # to the newly saved card
        data = {"card": organization.customer().card_display}
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


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = "__all__"
        read_only_fields = ("accepted_at", "rejected_at", "created_at")
