# Django
from django.conf import settings
from django.urls import reverse


class AvatarMixin(object):
    """Mixin for models with an avatar"""

    @property
    def avatar_url(self):
        if self.avatar and self.avatar.url.startswith("http"):
            return self.avatar.url
        elif self.avatar:
            return f"{settings.SQUARELET_URL}{self.avatar.url}"
        else:
            return self.default_avatar


class AdminLinkMixin(object):
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
