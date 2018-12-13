# Third Party
from rest_framework import serializers

# Local
from .models import Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False, source="id")

    class Meta:
        model = Organization
        fields = ("uuid", "name", "slug", "plan", "individual", "private", "updated_at")


class MembershipSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(source="organization.id")
    name = serializers.CharField(source="organization.name")
    slug = serializers.CharField(source="organization.slug")
    plan = serializers.IntegerField(source="organization.plan")
    individual = serializers.BooleanField(source="organization.individual")
    private = serializers.BooleanField(source="organization.private")
    updated_at = serializers.DateTimeField(source="organization.updated_at")

    class Meta:
        model = Membership
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "individual",
            "private",
            "updated_at",
            "admin",
        )
