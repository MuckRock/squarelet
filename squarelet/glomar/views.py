# Django
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import DetailView, TemplateView

# Squarelet
from squarelet.organizations.models import Organization
from squarelet.users.models import User


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict access to staff users"""

    def test_func(self):
        return self.request.user.is_staff


class GlomarDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "glomar/dashboard.html"


class GlomarUserDetailView(StaffRequiredMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"
    template_name = "glomar/user_detail.html"
    context_object_name = "target_user"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.object
        ind_org = user.individual_organization

        # Location from the individual organization
        context["city"] = ind_org.city
        context["state"] = ind_org.state
        context["country"] = ind_org.country

        # Individual plan (subscription on the individual org)
        context["individual_plan"] = ind_org._plan

        # Verification
        context["verified_journalist"] = user.verified_journalist()
        context["verified_emails"] = user.get_verified_emails()

        # Org memberships (non-individual orgs)
        memberships = (
            user.memberships.filter(organization__individual=False)
            .select_related("organization", "organization___plan")
            .order_by("organization__name")
        )
        # Attach plan_name since templates can't access _plan
        for m in memberships:
            m.plan_name = getattr(m.organization._plan, "name", "Free")
        context["memberships"] = memberships

        return context


class GlomarOrganizationDetailView(StaffRequiredMixin, DetailView):
    model = Organization
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "glomar/organization_detail.html"
    context_object_name = "org"

    def get_queryset(self):
        return Organization.objects.filter(individual=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.object

        context["plan"] = org._plan
        context["verified_journalist"] = org.verified_journalist

        # Members sorted admins-first, then by username
        memberships = (
            org.memberships.select_related("user")
            .order_by("-admin", "user__username")
        )
        context["memberships"] = memberships

        return context
