# Standard Library
import random
import re
import string

# Third Party
from rest_framework import serializers

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer

# Local
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """This is read by client sites to pull data over
    It is written to by client sites only for minireg functionality
    """

    uuid = serializers.UUIDField(required=False, source="id")
    preferred_username = serializers.CharField(source="username")
    picture = serializers.CharField(source="avatar_url")
    email = serializers.SerializerMethodField()
    email_verified = serializers.SerializerMethodField()
    organizations = MembershipSerializer(
        many=True, read_only=True, source="memberships"
    )

    class Meta:
        model = User
        fields = (
            "uuid",
            "name",
            "preferred_username",
            "updated_at",
            "picture",
            "email",
            "email_verified",
            "organizations",
        )

    def create(self, validated_data):
        if "preferred_username" in validated_data:
            validated_data["preferred_username"] = self.unique_username(
                validated_data["preferred_username"]
            )
        return super().create(validated_data)

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

    def get_primary_email_field(self, obj, field, default):
        if obj.primary_emails:
            email = obj.primary_emails[0]
            return getattr(email, field, default)
        else:
            return default

    def get_email(self, obj):
        return self.get_primary_email_field(obj, "email", "")

    def get_email_verified(self, obj):
        return self.get_primary_email_field(obj, "verified", False)
