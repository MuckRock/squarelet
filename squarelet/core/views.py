# Django
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse, HttpResponseServerError, JsonResponse
from django.http.response import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic.base import RedirectView, TemplateView

# Standard Library
import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Third Party
from pyairtable.formulas import match

# Squarelet
from squarelet.core.models import Alert, Category, NewsletterSignup, Provider, Resource


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

    def create_search_formula(self, query=None, category=None, provider=None):
        params = []
        if settings.ENV == "prod":
            status = '{Status} = "Accepted"'
            show = 'OR({Show?} = "Ready", {Show?} = "Kondo")'
            params += [f"AND({status}, {show})"]
        if query:
            search_fields = [
                f'SEARCH(LOWER("{query}"), LOWER({{Name}}))',
                f'SEARCH(LOWER("{query}"), LOWER({{Short Description}}))',
                f'SEARCH(LOWER("{query}"), LOWER({{Category}}))',
            ]
            params += [f"OR({', '.join(search_fields)})"]
        if category:
            params += [f'FIND("{category}", {{Category}})']
        if provider:
            params += [f'FIND("{provider}", {{Provider ID}})']
        formula = f"AND({', '.join(params)})"
        return formula

    def get_alerts(self, user):
        """Fetch relevant alert messages"""
        view = "Logged Out"
        if user.is_authenticated:
            view = "Logged In"
            if user.is_hub_eligible():
                view = "Hub Eligible"
        alerts = cache.get(f"erh_alerts_{view}")
        if not alerts:
            print("Cache miss. Fetching alerts…")
            alerts = Alert.all(view=view)
            cache.set(f"erh_alerts_{view}", alerts, settings.AIRTABLE_CACHE_TTL)
        return alerts

    def get_all_resources(self):
        resources = cache.get("erh_resources")
        if not resources:
            print("Cache miss. Fetching resources…")
            resources = Resource.all(formula=self.create_search_formula())
            cache.set("erh_resources", resources, settings.AIRTABLE_CACHE_TTL)
        return resources

    def get_all_providers(self):
        providers = cache.get("erh_providers")
        if not providers:
            print("Cache miss. Fetching providers…")
            providers = Provider.all(
                sort=["Name"], formula="{Has Live Resource} = 'Accepted'"
            )
            cache.set("erh_providers", providers, settings.AIRTABLE_CACHE_TTL)
        return providers

    def get_all_categories(self):
        categories = cache.get("erh_categories")
        if not categories:
            print("Cache miss. Fetching categories…")
            categories = Category.all(
                view="All Categories", formula=match({"Status": "Published"})
            )
            cache.set("erh_categories", categories, settings.AIRTABLE_CACHE_TTL)
        return categories

    def get_homepage_categories(self):
        categories = cache.get("erh_homepage_categories")
        if not categories:
            print("Cache miss. Fetching categories…")
            categories = Category.all(
                view="All Categories",
                formula=match({"Status": "Published", "Show on Homepage": True}),
            )
            # only include Accepted and Ready resources in the category
            for category in categories:
                category.resources = [
                    resource
                    for resource in category.resources
                    if (resource.status == "Accepted" and resource.visible == "Ready")
                ]
            cache.set(
                "erh_homepage_categories", categories, settings.AIRTABLE_CACHE_TTL
            )
        return categories

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
        if settings.ERH_CATALOG_ENABLED:
            resources = None
            # handle searching of resources
            query = self.request.GET.get("query")
            category = self.request.GET.get("category")
            provider = self.request.GET.get("provider")
            if query or category or provider:
                # not caching search results — they're too variable
                resources = Resource.all(
                    formula=self.create_search_formula(query, category, provider)
                )
            context["search"] = {
                "query": query or "",
                "category": category or "",
                "provider": provider or "",
                "category_choices": self.get_all_categories(),
                "provider_choices": self.get_all_providers(),
            }
            if provider:
                context["search"]["provider_name"] = Provider.from_id(provider).name

            context["resources"] = resources
            context["categories"] = self.get_homepage_categories()
            context["alerts"] = self.get_alerts(self.request.user)

        return context


class ERHResourceView(TemplateView):

    template_name = "core/erh_resource.html"

    def get_alerts(self, user):
        """Fetch relevant alert messages"""
        view = "Logged Out"
        if user.is_authenticated:
            view = "Logged In"
            if user.is_hub_eligible():
                view = "Hub Eligible"
        alerts = cache.get(f"erh_alerts_{view}")
        if not alerts:
            print("Cache miss. Fetching alerts…")
            alerts = Alert.all(view=view)
            cache.set(f"erh_alerts_{view}", alerts, settings.AIRTABLE_CACHE_TTL)
        return alerts

    def get_access_text(self, cost, is_expired):
        if is_expired:
            return "Expired"
        elif cost == "Free":
            return "Access for Free"
        elif cost == "Gated":
            return "Apply for Access"
        elif cost == "Paid":
            return "Access (Paid)"
        else:
            return "Access"

    def get_access_url(self, resource, user):
        url = resource.accessUrl or resource.homepageUrl
        if not url:
            return ""
        if (user.is_authenticated):
            # Parse the URL into components
            # to prefill field names
            url_parts = list(urlparse(url))
            org = user.organizations.filter(individual=False).first()
            # Check if the host is 'airtable.com'.
            # If it isn't, don't apply prefill arguments.
            if url_parts[1] != "airtable.com":
                return url
            # Get existing query parameters and update them with the record's parameters
            query = parse_qs(url_parts[4])
            if not org:
                query.update(
                    {
                        "prefill_Contact Name": user.safe_name(),
                        "prefill_Email address": user.email,
                    }
                )
            else:
                query.update(
                    {
                        "prefill_Contact Name": user.safe_name(),
                        "prefill_Email address": user.email,
                        "prefill_News organization": org.name,
                    }
                )
                if org.urls.first():
                    query.update({"prefill_Website": org.urls.first().url})
            # Encode the updated query parameters
            url_parts[4] = urlencode(query, doseq=True)
            # Reconstruct the final URL
            final_url = urlunparse(url_parts)
            return final_url
        return url

    def get_context_data(self, **kwargs):
        """Get the resource based on the ID in the url path. Return 404 if not found."""
        context = super().get_context_data()
        q_cache = self.request.GET.get("cache")

        if self.request.user.is_authenticated:
            context["can_access_hub"] = (
                self.request.user.is_hub_eligible() and settings.ERH_CATALOG_ENABLED
            )
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

        try:
            # get the resource
            cache_key = f"erh_resource/{kwargs['id']}"
            resource = cache.get(cache_key)
            if not resource or q_cache == "0":
                print("Cache miss. Fetching resource…")
                resource = Resource.from_id(kwargs["id"])
                cache.set(cache_key, resource, settings.AIRTABLE_CACHE_TTL)
            # show the resource page if the status is accepted
            # and the visibility is "Ready" or "Kondo"
            show = resource.status == "Accepted" and (
                resource.visible in ["Ready", "Kondo"]
            )
            if not show:
                raise Http404
            context["resource"] = resource
        except:
            raise Http404

        now = timezone.now()
        is_expired = (
            resource.expiration_date is not None and resource.expiration_date < now
        )

        context["access_text"] = self.get_access_text(resource.cost, is_expired)
        context["access_url"] = self.get_access_url(resource, self.request.user)
        context["is_expired"] = is_expired
        context["alerts"] = self.get_alerts(self.request.user)

        return context


class ERHAboutView(TemplateView):

    template_name = "core/erh_about.html"


def newsletter_subscription(request):
    if request.method == "POST":
        try:
            # Get the JSON data from the payload
            data = json.loads(request.body)
            name = data.get("name")
            email = data.get("email")
            organization = data.get("organization")
            # Create the record in Airtable
            signup = NewsletterSignup(email=email, name=name, organization=organization)
            signup.save()
            # Send a successful response
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                # Return JSON response for AJAX request
                data = {
                    "status": "success",
                    "message": "Thanks for subscribing!",
                    "name": name,
                    "email": email,
                    "organization": organization,
                }
                return JsonResponse(data)
            else:
                # Handle non-AJAX request (normal form submission)
                return HttpResponse(
                    f"Form submitted successfully! Name: {name}, Email: {email}"
                )
        except json.JSONDecodeError as exception:
            # Send an error response
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                # Return JSON response for AJAX request
                data = {
                    "status": "error",
                    "message": f"An error occurred during signup. {exception}",
                    "name": name,
                    "email": email,
                    "organization": organization,
                }
                return JsonResponse(data)
            else:
                # Handle non-AJAX request (normal form submission)
                return HttpResponseServerError(
                    f"""
                      An error occurred during signup.
                      Name: {name}
                      Email: {email}
                      Organization: {organization}
                    """
                )
    # For all other request types, redirect to the landing page
    return redirect("erh_landing")
