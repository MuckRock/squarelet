# Django
from django.conf import settings


class PressPassCookieMiddleware:
    """Set the cookie domain only for PressPass responses"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        host = request.get_host()
        print(response.cookies)
        print(host)
        if response.cookies and host == settings.PRESSPASS_DOMAIN:
            for cookie in response.cookies.values():
                cookie["domain"] = settings.PRESSPASS_COOKIE_DOMAIN
        return response
