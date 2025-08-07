# Third Party
from django_filters import rest_framework as filters

# Squarelet
from squarelet.organizations.models import OrganizationSubtype

# Local
from .models import Organization


class OrganizationFilter(filters.FilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    verified = filters.BooleanFilter(field_name="verified_journalist")
    individual = filters.BooleanFilter(field_name="individual")
    private = filters.BooleanFilter(field_name="private")
    subtypes = filters.ModelChoiceFilter(
        queryset=OrganizationSubtype.objects.select_related("type"),
        to_field_name="name",
    )

    class Meta:
        model = Organization
        fields = ["name", "verified", "individual", "private", "subtypes"]
