# Third Party
from django_filters import rest_framework as filters

# Local
from .models import Organization


class OrganizationFilter(filters.FilterSet):
    verified = filters.BooleanFilter(field_name="verified_journalist")
    individual = filters.BooleanFilter(field_name="individual")
    private = filters.BooleanFilter(field_name="private")

    class Meta:
        model = Organization
        fields = ["verified", "individual", "private"]
