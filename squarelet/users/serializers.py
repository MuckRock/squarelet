# Standard Library
import random
import re
import string

# Third Party
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken
from rest_framework import serializers

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer
from squarelet.users.models import User


class SocialTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialToken
        fields = ("token",)


class SocialAccountSerializer(serializers.ModelSerializer):
    tokens = SocialTokenSerializer(many=True, source="socialtoken_set")
    extra_data = serializers.JSONField()

    class Meta:
        model = SocialAccount
        fields = ("provider", "uid", "extra_data", "tokens")


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
            # TODO: Replace with user.email or user.primary_email
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
    social_accounts = SocialAccountSerializer(many=True, source="socialaccount_set")

    class Meta:
        model = User
        fields = (
            "bio",
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
            "social_accounts",
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
        username = base_username or "anonymous"
        while User.objects.filter(username__iexact=username).exists():
            rand_postfix = "".join(random.sample(string.ascii_letters, 8))
            username = f"{base_username}_{rand_postfix}"
        return username

    def validate_email(self, value):
        """Ensure email address is unique"""
        if EmailAddress.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("That email already has an account")
        return value
