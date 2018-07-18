
# Third Party
from rest_framework import serializers

# Local
from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "name", "email", "username")
