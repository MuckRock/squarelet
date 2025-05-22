# Django
from django.contrib.auth.models import AnonymousUser

# Standard Library
from unittest.mock import MagicMock

# Third Party
# Rest Framework
from rest_framework.test import force_authenticate


class ViewTestMixin:
    """Test mixin to help call views from tests"""

    # pylint: disable=protected-access, invalid-name

    def call_view(self, rf, user=None, data=None, params=None, **kwargs):
        if params is None:
            params = {}
        url = self.url.format(**kwargs)
        if user is None:
            user = AnonymousUser()
        if data is None:
            self.request = rf.get(url, params)
        else:
            self.request = rf.post(url, data)
        self.request.user = user
        self.request._messages = MagicMock()
        self.request.session = MagicMock()
        return self.view.as_view()(self.request, **kwargs)

    def assert_message(self, level, message):
        """Assert a message was added"""
        self.request._messages.add.assert_called_with(level, message, "")


class ViewSetTestMixin:
    """Test mixin to help call ViewSet endpoints from tests"""

    # pylint: disable=protected-access, invalid-name
    def call_action(
        self, rf, action, method="get", user=None, data=None, params=None, **kwargs
    ):
        if params is None:
            params = {}
        if user is None:
            user = AnonymousUser()

        url = self.url.format(**kwargs)

        method = method.lower()

        # Dynamically get the corresponding methods
        rf_method = getattr(rf, method)

        # For GET send params as query string
        if method in ("get"):
            request = rf_method(url, params)
        else:
            # For methods that usually accept body data (post, put, patch, delete)
            request = rf_method(url, data or {})

        force_authenticate(request, user=user)
        request._messages = MagicMock()
        request.session = MagicMock()

        view = self.view.as_view({method: action})
        return view(request, **kwargs)
