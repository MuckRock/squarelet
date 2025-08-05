# Third Party
from django_filters import rest_framework as filters

# Local
from .models import Organization


class OrganizationFilter(filters.FilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    verified = filters.BooleanFilter(field_name="verified_journalist")
    individual = filters.BooleanFilter(field_name="individual")
    private = filters.BooleanFilter(field_name="private")
    subtype = filters.CharFilter(method="filter_subtype", label="Subtype")

    def filter_subtype(self, queryset, value):
        return queryset.filter(subtypes__name=value)

    class Meta:
        model = Organization
        fields = ["name", "verified", "individual", "private"]
