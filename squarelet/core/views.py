# Django
from django.core.cache import cache
from django.urls import reverse
from django.db.models import Q
from django.views.generic.base import RedirectView, TemplateView
from squarelet.core.models import Resource
from squarelet.core.utils import resource_categories, get_category_choices

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

    def create_search_formula(self, query, category):
        params = []
        if query:
            searchFields = [
                'SEARCH(LOWER("{query}"), LOWER({{Name}}))'.format(query=query),
                'SEARCH(LOWER("{query}"), LOWER({{Short Description}}))'.format(query=query),
                'SEARCH(LOWER("{query}"), LOWER({{Category}}))'.format(query=query),
            ]
            params += ['OR({})'.format(', '.join(searchFields))]
        if category:
            params += ['FIND("{category}", {{Category}})'.format(category=category)]
        formula = 'AND({})'.format(', '.join(params))
        print(formula)
        return formula

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        if self.request.user.is_authenticated:
            context["can_access_hub"] = self.request.user.is_hub_eligible
            context["eligible_orgs"] = self.request.user.organizations.filter(
                Q(individual=False) &
                (Q(hub_eligible=True)
                 | Q(groups__hub_eligible=True)
                 | Q(parent__hub_eligible=True))
            )
            context["group_orgs"] = self.request.user.organizations.filter(individual=False)
            if self.request.user.is_hub_eligible:
                # handle searching of resources
                query = self.request.GET.get("query")
                category = self.request.GET.get("category")
                if query or category:
                  # don't cache search results — they're too variable, and they return subsets
                  resources = Resource.all(formula=self.create_search_formula(query, category))
                else:
                  # cache the full resource list
                  resources = cache.get_or_set("erh_resources", Resource.all(), 100)
                context["search"] = {
                    'query': query or "",
                    'category': category or "",
                    'category_choices': cache.get_or_set("erh_categories", get_category_choices(), 1000)
                }
                context["categories"] = resource_categories(resources)
        return context
