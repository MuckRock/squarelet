# Third Party
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


class UserSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(read_only=True)
    preferred_username = serializers.CharField(source="username", read_only=True)
    picture = serializers.CharField(source="avatar_url", read_only=True)
    email_verified = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    organizations = MembershipSerializer(
        many=True, read_only=True, source="memberships"
    )
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
        read_only_fields = fields

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

    def get_email(self, obj):
        return self.get_primary_email_field(obj, "email", "")
