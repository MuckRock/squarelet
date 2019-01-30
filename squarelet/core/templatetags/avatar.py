# Django
import hashlib
import random

from django import template
from django.utils.html import escape

register = template.Library()

@register.simple_tag
def avatar(profile_or_org, size=45):
  return '<div class="_cls-avatar"><img width="%d" height="%d" src="%s"></div>' % (size, size, escape(profile_or_org.avatar_url))
