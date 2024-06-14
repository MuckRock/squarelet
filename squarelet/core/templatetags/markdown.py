# Django
from django.template import Library
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

# Third Party
import bleach
import markdown

register = Library()


@register.filter(name="markdown")
@stringfilter
def markdown_filter(text, _safe=None):
    """Take the provided markdown-formatted text and convert it to HTML.
    This template tag is copied from the one used in `MuckRock/muckrock`.
    https://github.com/MuckRock/muckrock/blob/9c0620c13c74f5ab4dcb150f4b37de68d9f7aba5/muckrock/core/templatetags/tags.py#L289
    """
    # First render Markdown
    extensions = []
    #     "markdown.extensions.smarty",
    #     "markdown.extensions.tables",
    #     "markdown.extensions.codehilite",
    #     "markdown.extensions.fenced_code",
    #     "markdown.extensions.md_in_html",
    #     "pymdownx.magiclink",
    # ]
    markdown_text = markdown.markdown(text, extensions=extensions)
    # Next bleach the markdown
    allowed_tags = list(bleach.ALLOWED_TAGS) + [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "img",
        "iframe",
        "a",
    ]
    allowed_attributes = bleach.ALLOWED_ATTRIBUTES.copy()
    allowed_attributes.update(
        {
            "iframe": [
                "src",
                "width",
                "height",
                "frameborder",
                "marginheight",
                "marginwidth",
            ],
            "img": ["src", "alt", "title", "width", "height"],
            "a": ["href", "title", "name"],
        }
    )
    # allows bleaching to be avoided
    if _safe == "safe":
        bleached_text = markdown_text
    elif _safe == "strip":
        bleached_text = bleach.clean(
            markdown_text, tags=allowed_tags, attributes=allowed_attributes, strip=True
        )
    else:
        bleached_text = bleach.clean(
            markdown_text, tags=allowed_tags, attributes=allowed_attributes
        )
    return mark_safe(bleached_text)
