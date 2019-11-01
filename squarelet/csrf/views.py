from django.http import JsonResponse
from django.middleware.csrf import get_token

def get(request):
    return JsonResponse({'csrfToken': get_token(request)})

def ping(request):
    print(request.META)
    return JsonResponse({'result': 'OK'})
