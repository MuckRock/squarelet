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
    username = serializers.CharField(read_only=True)
    picture = serializers.CharField(source="avatar_url", read_only=True)
    email_verified = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()
    social_accounts = SocialAccountSerializer(many=True, source="socialaccount_set")

    class Meta:
        model = User
        fields = (
            "id",
            "uuid",
            "username",
            "name",
            "email",
            "email_failed",
            "email_verified",
            "is_agency",
            "organizations",
            "bio",
            "picture",
            "updated_at",
            "use_autologin",
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

    def get_organizations(self, obj):
        # Return list of organization IDs user is a member of
        return [m.organization_id for m in obj.memberships.all()]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            # Fetch the requesting user's orgs
            requester_org_ids = set(
                request.user.memberships.values_list("organization_id", flat=True)
            )
            target_org_ids = set(
                instance.memberships.values_list("organization_id", flat=True)
            )

            if not requester_org_ids.intersection(target_org_ids):
                # No shared orgs: remove sensitive fields
                data.pop("email", None)
                data.pop("email_verified", None)
        else:
            # Anonymous user
            data.pop("email", None)
            data.pop("email_verified", None)

        return data
