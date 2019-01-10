# Third Party
from rest_framework import serializers

# Local
from .models import Charge, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False, source="id")
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
            "date_update",
            "updated_at",
        )


class MembershipSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(source="organization.id")
    name = serializers.CharField(source="organization.name")
    slug = serializers.CharField(source="organization.slug")
    plan = serializers.CharField(source="organization.plan.slug")
    max_users = serializers.IntegerField(source="organization.max_users")
    individual = serializers.BooleanField(source="organization.individual")
    private = serializers.BooleanField(source="organization.private")
    date_update = serializers.DateField(source="organization.date_update")
    updated_at = serializers.DateTimeField(source="organization.updated_at")

    class Meta:
        model = Membership
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "max_users",
            "individual",
            "private",
            "date_update",
            "updated_at",
            "admin",
        )


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
        token = validated_data.get("token")
        if validated_data.get("save_card"):
            organization.save_card(token)
            token = None
        charge = Charge(
            organization=organization,
            amount=validated_data["amount"],
            description=validated_data["description"],
        )
        charge.make_charge(token)
        return charge

    def validate(self, attrs):
        """Must supply token if saving card"""
        if attrs.get("save_card") and not attrs.get("token"):
            raise serializers.ValidationError(
                "Must supply a token if save card is true"
            )
        return attrs
