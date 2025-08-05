# Django
from django.db.models.expressions import F

# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.organizations.models import (
    Charge,
    Membership,
    Organization,
    OrganizationSubtype,
)


def resolve_subtype_names_to_pks(subtype_names):
    """
    Given a list of subtype names, return a list of OrganizationSubtype PKs.
    """
    if not isinstance(subtype_names, list):
        raise serializers.ValidationError(
            {"subtypes": "Must be a list of subtype names."}
        )
    subtype_pks = []
    for name in subtype_names:
        try:
            subtype = OrganizationSubtype.objects.get(name=name)
            subtype_pks.append(subtype.pk)
        except OrganizationSubtype.DoesNotExist:
            raise serializers.ValidationError(
                {"subtypes": f"Invalid subtype name: {name}"}
            )
    return subtype_pks


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    merged = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    subtypes = serializers.ListField(
        child=serializers.CharField(),
        source="get_subtype_names",
        required=False,
        allow_null=True,
    )

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
        )

    def to_internal_value(self, data):
        """Adds custom handling for subtypes"""
        ret = super().to_internal_value(data)
        subtype_names = data.get("subtypes")
        if subtype_names is not None:
            ret["subtypes"] = resolve_subtype_names_to_pks(subtype_names)
        return ret


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
