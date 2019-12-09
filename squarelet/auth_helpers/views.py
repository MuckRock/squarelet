# Django
from django.http.response import JsonResponse
from django.shortcuts import render


def check(request):
    return JsonResponse({"authenticated": request.user.is_authenticated})
