# Django
from django.http import Http404


class ContextHttp404(Http404):
    """Http404 that carries extra template context for the 404 page."""

    def __init__(self, *args, context=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context or {}
