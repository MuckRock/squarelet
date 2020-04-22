# Third Party
from allauth.account.models import EmailAddress
from rest_framework import serializers


class PressPassEmailAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailAddress
        fields = ("email", "verified", "primary")
