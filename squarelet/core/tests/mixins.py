# Django
from django.contrib.auth.models import AnonymousUser

# Standard Library
from unittest.mock import MagicMock


class ViewTestMixin:
    """Test mixin to help call views from tests"""

    # pylint: disable=protected-access

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
