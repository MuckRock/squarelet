# Django
from django import template
from django.utils.html import format_html

# Third Party
from sorl.thumbnail import get_thumbnail
from sorl.thumbnail.helpers import ThumbnailError

# Squarelet
from squarelet.users.models import User

register = template.Library()


@register.simple_tag
def avatar(profile_or_org, size=45):
    """
    Render an avatar image with actual resizing using sorl-thumbnail.

    Args:
        profile_or_org: User or Organization object with an avatar
        size: Size in pixels for the square avatar (default 45)

    Returns:
        HTML string with resized avatar image
    """
    if profile_or_org is not None and profile_or_org.avatar:
        # Generate a resized thumbnail
        try:
            thumbnail = get_thumbnail(
                profile_or_org.avatar,
                f"{size}x{size}",
                crop="center",
                quality=85,
            )
            src = thumbnail.url
        except (ThumbnailError, IOError, OSError):
            # Fallback to default avatar if thumbnail generation fails
            src = User.default_avatar
    else:
        src = User.default_avatar

    return format_html(
        '<div class="_cls-avatar"><img width="{size}" height="{size}" src="{src}">'
        "</div>",
        size=size,
        src=src,
    )
