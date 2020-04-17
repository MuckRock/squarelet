# Django
import json
from django.http.response import (
    JsonResponse,
)
from allauth.account.forms import AddEmailForm
from allauth.account.views import EmailView as AllAuthEmailView


class EmailView(AllAuthEmailView):
    """Subclass of All Auth Email View """

    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)
        if "action_add" in data:
            form = AddEmailForm(data=data, user=request.user)

            if form.is_valid():
                email_address = form.save(self.request)

                return JsonResponse({"status": "OK"})
            else:
                return JsonResponse({"status": "error", "message": "Please provide a valid email address."})

