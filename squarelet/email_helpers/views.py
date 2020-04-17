# Django
import json
from django.http.response import (
    JsonResponse,
)
from allauth.account.adapter import get_adapter
from allauth.account.forms import AddEmailForm
from allauth.account.models import EmailAddress
from allauth.account.views import EmailView as AllAuthEmailView


class AddEmailView(AllAuthEmailView):
    """Subclass of All Auth Email View """

    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)

        form = AddEmailForm(data=data, user=request.user)

        if form.is_valid():
            email_address = form.save(self.request)

            return JsonResponse({"status": "OK"})
        else:
            return JsonResponse({"status": "error", "message": "Please provide a valid email address."})

class SendEmailView(AllAuthEmailView):
    """SendEmailView: Subclass of All Auth Email View """

    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)
        # resend email confirmation
        email = data.get(email)
        email_address = EmailAddress.objects.get(
            user=request.user,
            email=email,
        )
        get_adapter(request).add_message(
            request,
            messages.INFO,
            'account/messages/'
            'email_confirmation_sent.txt',
            {'email': email})
        email_address.send_confirmation(request)
        return JsonResponse({"status": "OK"})

class RemoveEmailView(AllAuthEmailView):
    """RemoveEmailView: Subclass of All Auth Email View """

    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)
        # remove (non-primary) email address from user
        email = data.get(email)
        email_address = EmailAddress.objects.get(
            user=request.user,
            email=email,
        )
        if email_address.primary:
            get_adapter(request).add_message(
                request,
                messages.ERROR,
                'account/messages/'
                'cannot_delete_primary_email.txt',
                {"email": email})
            return JsonResponse({"status": "error", "message": "You cannot delete the primary email address."})
        else:
            email_address.delete()
            return JsonResponse({"status": "OK"})

class PrimaryEmailView(AllAuthEmailView):
    """PrimaryEmailView: Subclass of All Auth Email View """

    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)
        # set an email address as primary
        email = data.get(email)
        email_address = EmailAddress.objects.get_for_user(
            user=request.user,
            email=email
        )
        # NOTE this feels like a lot of code copy & pasting
        # unfortunately this functionality is only defined in private functions
        # in allauth, so I'm not sure what the right way to do it otherwise is:
        # https://github.com/pennersr/django-allauth/blob/eaf6e96661a04ca1e9e8418ec1630646979823bd/allauth/account/views.py#L409-L414

        if not email_address.verified and \
                EmailAddress.objects.filter(user=request.user,
                                            verified=True).exists():
            get_adapter(request).add_message(
                request,
                messages.ERROR,
                'account/messages/'
                'unverified_primary_email.txt')
            return JsonResponse({"status": "error", "message": "You cannot make an unverified email address primary."})
        else:
            # Sending the old primary address to the signal
            # adds a db query.
            try:
                from_email_address = EmailAddress.objects \
                    .get(user=request.user, primary=True)
            except EmailAddress.DoesNotExist:
                from_email_address = None
            email_address.set_as_primary()
            get_adapter(request).add_message(
                request,
                messages.SUCCESS,
                'account/messages/primary_email_set.txt')
            signals.email_changed \
                .send(sender=request.user.__class__,
                        request=request,
                        user=request.user,
                        from_email_address=from_email_address,
                        to_email_address=email_address)
            return JsonResponse({"status": "OK"})




