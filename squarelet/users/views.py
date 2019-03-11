# Django
# Standard Library
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
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

# Third Party
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout

# Squarelet
from squarelet.core.layout import Field
from squarelet.core.mixins import AdminLinkMixin
from squarelet.organizations.models import ReceiptEmail

# Local
from .models import User


class UserDetailView(LoginRequiredMixin, AdminLinkMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
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
        form.helper.layout = Layout(
            Fieldset("Name", Field("name")),
            Fieldset("Username", Field("username"))
            if "username" in form.fields
            else None,
            Fieldset("Avatar image", Field("avatar"), css_class="_cls-compactField"),
            Fieldset(
                "Autologin", Field("use_autologin"), css_class="_cls-compactField"
            ),
        )
        form.helper.form_tag = False
        return form

    def form_valid(self, form):
        self.object = form.save(commit=False)
        if self.request.user.username != self.object.username:
            self.object.can_change_username = False
        self.object.save()
        self.object.individual_organization.avatar = self.object.avatar
        self.object.individual_organization.name = self.object.username
        self.object.individual_organization.save()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        """The user object has the invalid data in it - refresh it from the database
        before displaying to the user
        """
        self.object.refresh_from_db()
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.object.username})

    def get_object(self, queryset=None):
        return User.objects.get(pk=self.request.user.pk)


class UserListView(LoginRequiredMixin, ListView):
    model = User


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
