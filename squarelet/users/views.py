# Django
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
<<<<<<< HEAD
from django.http.response import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import DetailView, ListView, RedirectView, UpdateView

=======
from django.http.response import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.urls import reverse
from django.views.generic import DetailView, ListView, RedirectView, UpdateView

# Standard Library
import hashlib
import hmac
import time

>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c
# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout

# Squarelet
from squarelet.core.layout import Field
<<<<<<< HEAD
=======
from squarelet.core.mixins import AdminLinkMixin
from squarelet.organizations.models import ReceiptEmail
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c

# Local
from .models import User


class UserDetailView(LoginRequiredMixin, AdminLinkMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_context_data(self, **kwargs):
<<<<<<< HEAD
        context = super().get_context_data()
=======
        context = super().get_context_data(**kwargs)
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c
        context["other_orgs"] = context["user"].organizations.filter(individual=False)
        return context


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class UserUpdateView(LoginRequiredMixin, UpdateView):
    model = User

    def get_form_class(self):
        """Include username in form if the user hasn't changed their username yet"""
        fields = ["name", "avatar", "use_autologin"]
        if self.object.can_change_username:
            self.fields = ["username"] + fields
        else:
            self.fields = fields
        return super().get_form_class()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.helper = FormHelper()
<<<<<<< HEAD
        form.helper.layout = Layout(Field("username"), Field("name"), Field("avatar"))
=======
        form.helper.layout = Layout(
            Field("username"), Field("name"), Field("avatar"), Field("use_autologin")
        )
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c
        form.helper.form_tag = False
        return form

    def form_valid(self, form):
        self.object = form.save(commit=False)
        if self.request.user.username != self.object.username:
            self.object.can_change_username = False
        self.object.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.object.username})

    def get_object(self, queryset=None):
        return User.objects.get(pk=self.request.user.pk)


class UserListView(LoginRequiredMixin, ListView):
    model = User
<<<<<<< HEAD
=======


def mailgun_webhook(request):
    """Handle mailgun webhooks to keep track of user emails that have failed"""

    def verify(params):
        """Verify that the message is from mailgun"""
        token = params.get("token", "")
        timestamp = params.get("timestamp", "")
        signature = params.get("signature", "")
        hmac_digest = hmac.new(
            key=settings.MAILGUN_ACCESS_KEY,
            msg=f"{timestamp}{token}",
            digestmod=hashlib.sha256,
        ).hexdigest()
        match = hmac.compare_digest(signature, str(hmac_digest))
        return match and int(timestamp) + 300 > time.time()

    if not verify(request.POST.get("signature")):
        return HttpResponseForbidden()

    event = request.POST["event-data"]
    if event["event"] != "failed":
        return HttpResponse("OK")

    email = event["recipient"]

    User.objects.filter(email=email).update(email_failed=True)
    ReceiptEmail.objects.filter(email=email).update(failed=True)
>>>>>>> 12ec74ebf3f5076b05785065adb2435d5017154c
