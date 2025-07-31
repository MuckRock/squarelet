# Third Party
from allauth.socialaccount.models import SocialAccount, SocialToken
from rest_framework import serializers

# Squarelet
from squarelet.organizations.serializers import MembershipSerializer
from squarelet.users.models import User


class UserSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    picture = serializers.CharField(source="avatar_url", read_only=True)
    organizations = serializers.PrimaryKeyRelatedField(read_only=True, many=True)

    class Meta:
        model = User
        fields = (
            "id",
            "uuid",
            "username",
            "name",
            "email",
            "is_agency",
            "organizations",
            "bio",
            "picture",
            "updated_at",
            "use_autologin",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            # Fetch the requesting user's orgs
            if not hasattr(self, "_cache_requester_org_ids"):
                self._cache_requester_org_ids = set(
                    request.user.memberships.values_list("organization_id", flat=True)
                )
            target_org_ids = set(o.pk for o in instance.organizations.all())

            if not self._cache_requester_org_ids.intersection(target_org_ids):
                # No shared orgs: remove sensitive fields
                data.pop("email", None)
        else:
            # Anonymous user
            data.pop("email", None)

        return data
