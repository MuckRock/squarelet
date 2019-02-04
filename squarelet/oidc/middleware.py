"""Middleware for the OIDC app"""

# Standard Library
import threading
from collections import defaultdict

# Local
from . import utils

CACHE_INVALIDATION_SET = threading.local()


class CacheInvalidationSenderMiddleware:
    """Middleware to send cache invalidations at the end of the request
    This allows us to not send multiple cache invalidations for the same object
    during the same request
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """Send all cache invalidations after the view is finished"""
        CACHE_INVALIDATION_SET.set = defaultdict(set)

        try:
            response = self.get_response(request)
        finally:
            for model, uuids in CACHE_INVALIDATION_SET.set.items():
                utils.send_cache_invalidations(model, list(uuids))
            del CACHE_INVALIDATION_SET.set

        return response


def send_cache_invalidations(model, uuids):
    """Set a cache invalidation to be sent at the end of the request"""
    if not isinstance(uuids, list):
        uuids = [uuids]
    if hasattr(CACHE_INVALIDATION_SET, "set"):
        for uuid in uuids:
            CACHE_INVALIDATION_SET.set[model].add(uuid)
    else:
        # if there is no set, we are not in a request-response cycle
        # (ie celery or the REPL) - just send immediately
        utils.send_cache_invalidations(model, uuids)
