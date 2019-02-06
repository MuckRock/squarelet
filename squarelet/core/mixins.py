# Django
from django.conf import settings


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
