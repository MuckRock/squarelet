# Third Party
from rest_framework import serializers

# Local
from .models import Membership, Organization


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
