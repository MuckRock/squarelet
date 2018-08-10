
# Third Party
from rest_framework import serializers

# Local
from .models import User


class UserSerializer(serializers.ModelSerializer):
    # this is read-only by default, so we declare it manually
    id = serializers.UUIDField()

    class Meta:
        model = User
        fields = ("id", "name", "email", "username")
