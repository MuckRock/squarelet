# Django
from django.contrib.postgres.search import SearchQuery, SearchVector

# Standard Library
import re

# Third Party
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

# Squarelet
from squarelet.users.fe_api.serializers import UserSearchSerializer, UserSerializer
from squarelet.users.models import User


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated,)
    lookup_field = "id"
    swagger_schema = None

    def get_serializer_class(self):
        if self.action == "list":
            return UserSearchSerializer
        return UserSerializer

    def get_queryset(self):
        if self.action == "list":
            qs = User.objects.get_searchable(self.request.user)
            search = self.request.query_params.get("search", "").strip()
            if search:
                # Full-text search with prefix matching.
                # Strip tsquery special characters so raw queries are safe.
                sanitized = re.sub(r"[&|!<>():*@.\\\"]", " ", search).strip()
                if sanitized:
                    vector = SearchVector("username", "name", "email")
                    terms = sanitized.split()
                    tsquery = " & ".join(f"{t}:*" for t in terms)
                    query = SearchQuery(tsquery, search_type="raw")
                    qs = qs.annotate(search=vector).filter(search=query)
            return qs
        return User.objects.prefetch_related("organizations")
