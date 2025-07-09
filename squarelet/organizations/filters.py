from django_filters import rest_framework as filters
from .models import Organization

class OrganizationFilter(filters.FilterSet):
    verified = filters.BooleanFilter(field_name="verified_journalist")
    individual = filters.BooleanFilter(field_name="individual")

    class Meta:
        model = Organization
        fields = ["verified", "individual"]
