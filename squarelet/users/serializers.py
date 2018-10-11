# Standard Library
import random
import re
import string

# Third Party
from rest_framework import serializers

# Local
from .models import User


class UserSerializer(serializers.ModelSerializer):
    # this is read-only by default, so we declare it manually
    id = serializers.UUIDField(required=False)
    # we do not want the default validation for username, as we can uniqify the name
    username = serializers.CharField()

    class Meta:
        model = User
        fields = ("id", "name", "email", "username")

    def create(self, validated_data):
        if "username" in validated_data:
            validated_data["username"] = self.unique_username(
                validated_data["username"]
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
