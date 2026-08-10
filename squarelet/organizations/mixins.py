# Django
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin
from django.http import Http404
from django.shortcuts import redirect

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.organizations.models import ProfileChangeRequest


class OrganizationAdminMixin(UserPassesTestMixin):
    """Only allow access to organization admins"""

    def test_func(self):
        is_staff = self.request.user.is_staff
        is_admin = self.request.user.is_authenticated and self.get_object().has_admin(
            self.request.user
        )
        return is_admin or is_staff


class OrganizationPermissionMixin(PermissionRequiredMixin):
    """Check a permission against the organization object.

    Works with both django-rules (dynamic) and ModelBackend (DB-assigned).
    Authenticated users without permission get 403; anonymous users are redirected.
    """

    def has_permission(self):
        user = self.request.user
        obj = self.get_object()
        perms = self.get_permission_required()
        return all(user.has_perm(perm, obj) for perm in perms)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            self.raise_exception = True
        return super().handle_no_permission()


class IndividualMixin:
    """Adapt a organizational view for a user's individual organization"""

    def get_object(self, queryset=None):
        # pylint: disable=unused-argument
        if self.request.user.is_authenticated:
            return self.request.user.individual_organization
        else:
            return None


class VerifiedJournalistMixin(UserPassesTestMixin):
    """Only allow access to admins of organizations that are marked verified"""

    def test_func(self):
        # Check if the user is authenticated, an admin
        # and the organization is verified as a journalist
        organization = self.get_object()
        return (
            self.request.user.is_authenticated
            and organization.verified_journalist
            and organization.has_admin(self.request.user)
        )


class ResolveOrganizationSlugMixin:
    """Resolve an org by slug, or look for a matching change request
    and return a redirect if one is found."""

    def get(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
        except Http404:
            slug_redirect = self.get_slug_redirect(request.user)
            if slug_redirect is not None:
                return slug_redirect
            raise ContextHttp404(context={"user_orgs": self.get_user_orgs(request)})

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_slug_redirect(self, user):
        slug = self.kwargs.get("slug")
        change_request = (
            ProfileChangeRequest.objects.filter(previous__slug=slug, status="accepted")
            .select_related("organization")
            .order_by("-updated_at")
            .first()
        )
        if change_request is None:
            return None
        org = change_request.organization
        if not user.has_perm("organizations.view_organization", org):
            return None
        return redirect(org.get_absolute_url(), permanent=True)

    def get_user_orgs(self, request):
        user = request.user
        if not hasattr(user, "organizations"):
            return []
        return user.organizations.filter(individual=False).order_by("name")
