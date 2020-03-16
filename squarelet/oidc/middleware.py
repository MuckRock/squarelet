"""Middleware for the OIDC app"""

# Standard Library
import threading
from collections import defaultdict

# Squarelet
from squarelet.oidc import utils

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
        initialize_cache_invalidation_set()

        try:
            response = self.get_response(request)
        finally:
            send_cache_invalidation_set()
            delete_cache_invalidation_set()

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
        # (ie celery or the REPL) and we have not manually initalized a batch set
        # just send immediately
        utils.send_cache_invalidations(model, uuids)


# these are pulled out to allow manually batching cache invalidations in
# non request-response cycle environments


def initialize_cache_invalidation_set():
    CACHE_INVALIDATION_SET.set = defaultdict(set)


def send_cache_invalidation_set():
    for model, uuids in CACHE_INVALIDATION_SET.set.items():
        utils.send_cache_invalidations(model, list(uuids))


def delete_cache_invalidation_set():
    del CACHE_INVALIDATION_SET.set
