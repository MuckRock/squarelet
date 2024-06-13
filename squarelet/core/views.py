# Django
from django.core.cache import cache
from django.db.models import Q
from django.http.response import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic.base import RedirectView, TemplateView

# Squarelet
from squarelet.core.models import Provider, Resource
from squarelet.core.utils import get_category_choices, resource_categories


class HomeView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return reverse(
                "users:detail", kwargs={"username": self.request.user.username}
            )
        else:
            return reverse("select_plan")


class ERHLandingView(TemplateView):

    template_name = "core/erh_landing.html"

    def create_search_formula(self, query, category, provider):
        params = []
        if query:
            search_fields = [
                f'SEARCH(LOWER("{query}"), LOWER({{Name}}))',
                f'SEARCH(LOWER("{query}"), LOWER({{Short Description}}))',
                f'SEARCH(LOWER("{query}"), LOWER({{Category}}))',
            ]
            params += [f"OR({', '.join(search_fields)}"]
        if category:
            params += [f'FIND("{category}", {{Category}})']
        if provider:
            params += [f'FIND("{provider}", {{Provider ID}})']
        formula = f"AND({', '.join(params)})"
        return formula

    def get_all_resources(self):
        return Resource.all()

    def get_all_providers(self):
        return Provider.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            context["can_access_hub"] = self.request.user.is_hub_eligible()
            context["eligible_orgs"] = self.request.user.organizations.filter(
                Q(individual=False)
                & (
                    Q(hub_eligible=True)
                    | Q(groups__hub_eligible=True)
                    | Q(parent__hub_eligible=True)
                )
            )
            context["group_orgs"] = self.request.user.organizations.filter(
                individual=False
            )
            if self.request.user.is_hub_eligible():
                # handle searching of resources
                query = self.request.GET.get("query")
                category = self.request.GET.get("category")
                provider = self.request.GET.get("provider")
                if query or category or provider:
                    # not caching search results — they're too variable
                    resources = Resource.all(
                        formula=self.create_search_formula(query, category, provider)
                    )
                else:
                    # cache the full resource list
                    resources = cache.get_or_set(
                        "erh_resources", self.get_all_resources(), 1000
                    )
                context["search"] = {
                    "query": query or "",
                    "category": category or "",
                    "provider": provider or "",
                    "category_choices": cache.get_or_set(
                        "erh_categories", get_category_choices(), 1000
                    ),
                    "provider_choices": cache.get_or_set(
                        "erh_providers", self.get_all_providers(), 1000
                    ),
                }
                context["resources"] = resources
                context["categories"] = resource_categories(resources)
        return context


class ERHResourceView(TemplateView):

    template_name = "core/erh_resource.html"

    def get(self, request, *args, **kwargs):
        can_view = (
            self.request.user.is_authenticated and self.request.user.is_hub_eligible()
        )
        print(can_view)
        if can_view:
            return super().get(request, *args, **kwargs)
        else:
            return redirect("erh_landing")

    def get_context_data(self, **kwargs):
        """Get the resource based on the ID in the url path. Return 404 if not found."""
        context = super().get_context_data()

        try:
            # get the resource
            cache_key = f"erh_resource/{kwargs['id']}"
            resource = cache.get_or_set(cache_key, Resource.from_id(kwargs["id"]), 300)
            context["resource"] = resource
        except:
            raise Http404

        return context
