"""Helpers for exchanging application tokens for JWTs and logging their use"""

# Standard Library
import logging

# Third Party
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)


def client_ip(request):
    """Best-effort client address for logging"""
    if request is None:
        return "-"
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "-")


def log_event(token, event, request):
    """Log token usage, attributed as `<username>:<token name>`"""
    logger.info(
        "app_token=%s id=%s event=%s ip=%s",
        token.log_label,
        token.pk,
        event,
        client_ip(request),
    )


def log_rejection(reason, request, prefix="-"):
    """Log a failed token use; never log the secret"""
    logger.info(
        "app_token=- event=rejected reason=%s prefix=%s ip=%s",
        reason,
        prefix,
        client_ip(request),
    )


def token_prefix(plaintext):
    """The public prefix of a plaintext token, if it is well-formed"""
    parts = (plaintext or "").split("_", 2)
    return parts[1] if len(parts) == 3 else "-"


def jwt_for_token(token):
    """Mint a JWT pair for an application token's user

    The claims are copied to access tokens and survive refresh rotation:
    - `app_token_id` lets refreshes be refused once the token is revoked
    - `app` attributes requests to `<username>:<token name>`
    - `staff` tells client sites whether staff access may be used
    """
    refresh = RefreshToken.for_user(token.user)
    refresh["app_token_id"] = token.pk
    refresh["app"] = token.log_label
    refresh["staff"] = token.allow_staff and token.user.is_staff
    return refresh
