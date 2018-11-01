"""Functions to update information on other sites when someone updates their
information on squarelet"""

# Django
from django.conf import settings

# Third Party
import requests


def muckrock_api(path, data=None, method="patch"):
    if data is None:
        data = {}
    url = f"{settings.MUCKROCK_URL}/api_v1{path}"
    headers = {
        "Authorization": f"Token {settings.MUCKROCK_TOKEN}",
        "content-type": "application/json",
    }
    return requests.request(method, url, json=data, headers=headers)
