# Third Party
from allauth.account.models import EmailAddress
from rest_framework import serializers


class PressPassEmailAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailAddress
        fields = ("email", "verified", "primary")

    def validate(self, attrs):
        request = self.context.get("request")
        if request.data.get("action") == "update":
            if (
                not attrs["verified"]
                and EmailAddress.objects.filter(
                    user=request.user, verified=True
                ).exists()
            ):
                raise serializers.ValidationError(
                    "You can only make a verified email address primary."
                )

        if request.data.get("action") == "delete":
            if request.data["primary"]:
                raise serializers.ValidationError(
                    "You cannot delete your primary email address."
                )

        return attrs

    def is_valid_update(self, attrs):
        request = self.context.get("request")
        if (
            not attrs["verified"]
            and EmailAddress.objects.filter(
                user=request.user, verified=True
            ).exists()
        ):
            raise serializers.ValidationError(
                "You can only make a verified email address primary."
            )

        return attrs

    def is_valid_delete(self, email):
        if email.primary:
            raise serializers.ValidationError(
                "You cannot delete your primary email address."
            )
        return email
