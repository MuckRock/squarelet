# Standard Library
import random
import re
import string

# Third Party
from rest_framework import serializers

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer
from squarelet.users.models import User
from squarelet.organizations.models import (
    Membership,
    Invitation
)


class UserBaseSerializer(serializers.ModelSerializer):
    """This serializer is the base for both the read and write serializers"""

    uuid = serializers.UUIDField(required=False)
    preferred_username = serializers.CharField(source="username")
    picture = serializers.CharField(source="avatar_url", required=False)
    email_verified = serializers.SerializerMethodField()
    organizations = MembershipSerializer(
        many=True, read_only=True, source="memberships"
    )

    def get_primary_email_field(self, obj, field, default):
        if hasattr(obj, "primary_emails") and obj.primary_emails:
            email = obj.primary_emails[0]
            return getattr(email, field, default)
        elif not hasattr(obj, "primary_emails"):
            email = obj.emailaddress_set.filter(primary=True).first()
            if email:
                return getattr(email, field, default)

        return default

    def get_email_verified(self, obj):
        return self.get_primary_email_field(obj, "verified", False)


class UserReadSerializer(UserBaseSerializer):
    """Read serializer for user, for clients to pull data
    This reads email information from the primary EmailAddress object

    We do this to ensure that the verified email field is consistent with the email
    address.  The primary email address object email should match the user's
    email field.
    """

    email = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "email",
            "email_failed",
            "email_verified",
            "is_agency",
            "name",
            "organizations",
            "picture",
            "preferred_username",
            "updated_at",
            "use_autologin",
            "uuid",
        )

    def get_email(self, obj):
        return self.get_primary_email_field(obj, "email", "")


class UserWriteSerializer(UserBaseSerializer):
    """Write serializer for user, for miniregistration: registration via API
    This write's the email to the user email field
    """

    class Meta:
        model = User
        fields = (
            "email",
            "email_failed",
            "email_verified",
            "is_agency",
            "name",
            "organizations",
            "picture",
            "preferred_username",
            "updated_at",
            "use_autologin",
            "uuid",
        )
        extra_kwargs = {
            "email": {"required": False},
            "is_agency": {"required": False},
            "use_autologin": {"required": False, "default": True},
        }

    def create(self, validated_data):
        if "username" in validated_data:
            validated_data["username"] = self.unique_username(
                validated_data["username"]
            )
        user = User.objects.create_user(**validated_data)

        return user

    @staticmethod
    def unique_username(name):
        """Create a globally unique username from a name and return it."""
        # username can be at most 150 characters
        # strips illegal characters from username
        base_username = re.sub(r"[^\w\-.]", "", name)[:141]
        username = base_username
        while User.objects.filter(username__iexact=username).exists():
            username = "{}_{}".format(
                base_username, "".join(random.sample(string.ascii_letters, 8))
            )
        return username


class PressPassUserSerializer(serializers.ModelSerializer):
    """Serializer for the more traditional API for PressPass"""

    class Meta:
        model = User
        fields = (
            "name",
            "email",
            "email_failed",
            "avatar",
            "username",
            "created_at",
            "updated_at",
            "use_autologin",
            "uuid",
            "can_change_username",
        )
        extra_kwargs = {
            "email": {"read_only": True},
            "email_failed": {"read_only": True},
            "created_at": {"read_only": True},
            "updated_at": {"read_only": True},
            "can_change_username": {"read_only": True},
        }

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.instance and not self.instance.can_change_username:
                # pylint: disable=invalid-sequence-index
                self.fields["username"].read_only = True


class PressPassUserMembershipsSerializer(serializers.ModelSerializer):
    organization = serializers.SlugRelatedField(slug_field="uuid", read_only=True)

    class Meta:
        model = Membership
        fields = ("organization", "admin")
        extra_kwargs = {"admin": {"default": False}}


class PressPassUserInvitationsSerializer(serializers.ModelSerializer):
    organization = serializers.SlugRelatedField(slug_field="uuid", read_only=True)

    class Meta:
        model = Invitation
        fields = ("organization", "request")
        extra_kwargs = {"request": {"default": False}}
