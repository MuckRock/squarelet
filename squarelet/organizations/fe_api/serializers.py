# Django
from django.db.models.expressions import F

# Third Party
import stripe
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from sorl.thumbnail import get_thumbnail
from sorl.thumbnail.helpers import ThumbnailError

# Squarelet
from squarelet.organizations.models import Invitation, Membership, Organization
from squarelet.users.models import User


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    merged = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    member_count = serializers.IntegerField(read_only=True)
    users = serializers.PrimaryKeyRelatedField(
        many=True,
        read_only=True,
    )
    admins = serializers.SerializerMethodField()
    avatar_small = serializers.SerializerMethodField()
    avatar_medium = serializers.SerializerMethodField()

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
            "avatar_small",
            "avatar_medium",
            "merged",
        )

    def get_admins(self, obj):
        return [
            user.pk
            for user in obj.users.all()
            if any(
                m.admin and m.organization_id == obj.pk for m in user.memberships.all()
            )
        ]

    def get_avatar_small(self, obj):
        """Return a 50x50 thumbnail of the avatar."""
        if obj.avatar:
            try:
                thumbnail = get_thumbnail(
                    obj.avatar, "50x50", crop="center", quality=85
                )
                return thumbnail.url
            except (ThumbnailError, IOError, OSError):
                pass
        return obj.default_avatar

    def get_avatar_medium(self, obj):
        """Return a 150x150 thumbnail of the avatar."""
        if obj.avatar:
            try:
                thumbnail = get_thumbnail(
                    obj.avatar, "150x150", crop="center", quality=85
                )
                return thumbnail.url
            except (ThumbnailError, IOError, OSError):
                pass
        return obj.default_avatar

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
            rep.pop("users", None)
        else:
            is_member = user in instance.users.all()
            if not is_member:
                rep.pop("users", None)

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
