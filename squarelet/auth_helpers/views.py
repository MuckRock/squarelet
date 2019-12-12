# Django
from django.http.response import JsonResponse


def check(request):
    return JsonResponse({"authenticated": request.user.is_authenticated})
