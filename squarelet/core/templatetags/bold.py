# Django
from django import template

# Standard Library
import html

register = template.Library()


@register.simple_tag
def bold(highlight_text, full_text):
    text = html.escape(full_text)
    if highlight_text == "":
        return text

    result = ""

    while True:
        try:
            idx = text.index(highlight_text)
            result += text[:idx]
            result += "<b>" + text[idx : idx + len(highlight_text)] + "</b>"
            text = text[idx + len(highlight_text) :]
        except:
            break

    result += text
    return result
