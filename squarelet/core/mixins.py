# Django
from django.conf import settings
from django.urls import reverse


class AvatarMixin:
    """Mixin for models with an avatar"""

    @property
    def avatar_url(self):
        url = self.avatar.url if self.avatar else self.default_avatar
        return url if url.startswith("http") else f"{settings.SQUARELET_URL}{url}"


class AdminLinkMixin:
    """Add an admin link to a view for staff"""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_staff:
            meta = self.object._meta
            context["admin_link"] = reverse(
                f"admin:{meta.app_label}_{meta.model_name}_change",
                args=(self.object.pk,),
            )
        return context
