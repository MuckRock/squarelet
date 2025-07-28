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
    merged = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    member_count = serializers.SerializerMethodField()
    users = serializers.PrimaryKeyRelatedField(
        many=True,
        read_only=True,
    )
    admins = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "id",
            "uuid",
            "admins",
            "member_count",
            "users",
            "name",
            "slug",
            "max_users",
            "individual",
            "private",
            "verified_journalist",
            "updated_at",
            "payment_failed",
            "avatar_url",
            "merged",
        )

    def get_admins(self, obj):
        return list(
            obj.memberships.filter(admin=True).values_list("user_id", flat=True)
        )

    def get_member_count(self, obj):
        return obj.memberships.count()

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
