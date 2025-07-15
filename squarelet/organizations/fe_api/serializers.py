# Django
from django.db.models.expressions import F

# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.organizations.models import Invitation, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    # remove plan once all clients are updated to handle entitlements
    plan = serializers.SerializerMethodField()
    entitlements = serializers.SerializerMethodField()
    merged = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    member_count = serializers.SerializerMethodField()
    admins = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "id",
            "uuid",
            "admins",
            "member_count",
            "members",
            "name",
            "slug",
            "plan",
            "entitlements",
            "max_users",
            "individual",
            "private",
            "verified_journalist",
            "updated_at",
            "payment_failed",
            "avatar_url",
            "merged",
        )

    def get_plan(self, obj):
        return obj.plan.slug if obj.plan else "free"

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

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_admins(self, obj):
        return list(
            obj.memberships.filter(admin=True).values_list("user_id", flat=True)
        )

    def get_members(self, obj):
        return list(obj.memberships.values_list("user_id", flat=True))

    def to_representation(self, instance):
        rep = super().to_representation(instance)

        request = self.context.get("request", None)
        user = getattr(request, "user", None)

        # Remove admins and member_count if organization is individual
        if instance.individual:
            rep.pop("admins", None)
            rep.pop("member_count", None)

        # Only keep members if user is authenticated AND member of org
        if not user or not user.is_authenticated:
            rep.pop("members", None)
        else:
            is_member = instance.memberships.filter(user=user).exists()
            if not is_member:
                rep.pop("members", None)

        return rep


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


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = "__all__"
        read_only_fields = (
            "id",
            "uuid",
            "accepted_at",
            "rejected_at",
            "created_at",
            "user",
        )

    def perform_create(self, serializer):
        invitation = serializer.save()
        invitation.send()
