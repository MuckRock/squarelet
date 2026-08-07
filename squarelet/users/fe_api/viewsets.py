# Django
from django.contrib.postgres.search import SearchQuery, SearchVector

# Standard Library
import re

# Third Party
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

# Squarelet
from squarelet.organizations.models.organization import Organization
from squarelet.users.fe_api.serializers import UserSearchSerializer, UserSerializer
from squarelet.users.models import User


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (AllowAny,)
    lookup_field = "id"
    swagger_schema = None

    def get_serializer_class(self):
        if self.action == "list":
            return UserSearchSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if self.action == "list":
            if not user.is_authenticated:
                return User.objects.none()
            qs = User.objects.get_searchable(user).filter(is_active=True)
            search = self.request.query_params.get("search", "").strip()
            org = self.request.query_params.get("organization", "").strip()
            if org:
                viewable_org = Organization.objects.filter(slug=org).get_viewable(user)
                if not viewable_org.exists():
                    return User.objects.none()
                qs = qs.filter(organizations__in=viewable_org).order_by("-last_login")
            if search:
                # Full-text search with prefix matching.
                # Strip tsquery special characters so raw queries are safe.
                sanitized = re.sub(r"[&|!<>():*@.\\\"]", " ", search).strip()
                if sanitized:
                    vector = SearchVector("username", "name")
                    terms = sanitized.split()
                    tsquery = " & ".join(f"{t}:*" for t in terms)
                    query = SearchQuery(tsquery, search_type="raw")
                    qs = qs.annotate(search=vector).filter(search=query)
            return qs
        return User.objects.prefetch_related("organizations")
