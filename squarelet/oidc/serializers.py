# Third Party
from oidc_provider.models import Client
from rest_framework import serializers


class ClientSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = (
            "id",
            "name",
            "owner",
            "client_type",
            "client_id",
            "client_secret",
            "date_created",
            "website_url",
            "terms_url",
            "contact_email",
            "logo",
            "reuse_consent",
            "redirect_uris",
            "post_logout_redirect_uris",
        )
        extra_kwargs = {
            "client_id": {"read_only": True},
            "client_secret": {"read_only": True},
            "date_created": {"read_only": True},
            "logo": {"required": False},
            "redirect_uris": {"source": "_redirect_uris"},
            "post_logout_redirect_uris": {"source": "_post_logout_redirect_uris"},
        }

    def get_owner(self, obj):
        return str(obj.owner.uuid)
