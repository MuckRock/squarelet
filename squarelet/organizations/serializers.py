
# Third Party
from rest_framework import serializers

# Local
from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "id",
            "name",
            "org_type",
            "individual",
            "private",
            "requests_per_month",
            "monthly_requests",
            "number_requests",
            "pages_per_month",
            "monthly_pages",
            "number_pages",
        )
