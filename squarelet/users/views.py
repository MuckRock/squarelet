# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http.response import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.views.generic import (
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)

# Standard Library
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

# Third Party
from allauth.account.mixins import NextRedirectMixin
from allauth.account.utils import (
    get_next_redirect_url,
    has_verified_email,
    send_email_confirmation,
)
from allauth.account.views import LoginView as AllAuthLoginView
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout

# Squarelet
from squarelet.core.forms import ImagePreviewWidget
from squarelet.core.layout import Field
from squarelet.core.mixins import AdminLinkMixin
from squarelet.organizations.models import Invitation, ReceiptEmail
from squarelet.services.models import Service

# Local
from .models import User


class UserDetailView(LoginRequiredMixin, AdminLinkMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def dispatch(self, request, *args, **kwargs):
        if kwargs["username"] != request.user.username and not request.user.is_staff:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_invitations(self, user):
        """Check if the user has any pending invitations"""
        invitations = Invitation.objects.get_pending().filter(user=user)
        for invitation in invitations:
            url = reverse("organizations:invitation", args=(invitation.uuid,))
            # TODO: move this to context data instead of displaying a success toast
            messages.success(
                self.request,
                format_html(
                    '<a href="{}">'
                    "Click here to view your invitation for {}"
                    "</a>&nbsp;&nbsp",
                    url,
                    invitation.organization,
                ),
            )

    def get(self, request, *args, **kwargs):
        if kwargs["username"] == request.user.username:
            self.get_invitations(request.user)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["other_orgs"] = (
            context["user"]
            .organizations.filter(individual=False)
            .get_viewable(self.request.user)
        )
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
            (
                Fieldset("Username", Field("username"))
                if "username" in form.fields
                else None
            ),
            Fieldset("Avatar image", Field("avatar"), css_class="_cls-compactField"),
            Fieldset(
                "Autologin", Field("use_autologin"), css_class="_cls-compactField"
            ),
        )
        form.helper.form_tag = False
        form.fields["avatar"].widget = ImagePreviewWidget()
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


class LoginView(AllAuthLoginView):        
    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to provide onboarding steps, if needed"""
        # handle the request as usual, but hold onto the response
        response = super().dispatch(request, *args, **kwargs)
        # when logging in, a POST is sent
        is_post = request.method == "POST"
        # if the login succeeded, then the user is authenticated
        user = self.request.user
        if is_post and user.is_authenticated:
            next_url = self.get_success_url()
            intent = request.GET.get("intent")
            # Check the user's account status
            if not has_verified_email(user):
                # If the user has not verified their email,
                # send a new confirmation email and redirect
                send_email_confirmation(request, user, False, user.email)
                url = reverse("login_confirm_email")
                params = {}
                if next_url:
                    params['next'] = next_url
                if intent:
                    params['intent'] = intent
                if params:
                    url += '?' + urlencode(params)
                return redirect(url)
            # provide other onboarding checks and handlers here
        # return the default response
        return response

    def get(self, request, *args, **kwargs):
        """
        If the url_auth_token parameter is still present, it means the auth token failed
        to authenticate the user.  Redirect them to the nested next parameter instead of
        asking them to login
        """
        next_url = get_next_redirect_url(request)
        if "url_auth_token" in request.GET and next_url:
            return redirect(f"{settings.MUCKROCK_URL}{next_url}")
        return super().get(request, *args, **kwargs)


class EmailConfirmationView(NextRedirectMixin, TemplateView):
    template_name = "account/login_verification_sent.html"

    def get(self, request, *args, **kwargs):
        """If the user has a verified email, skip this page."""
        next_url = self.get_next_url()
        if self.request.user.is_authenticated and has_verified_email(self.request.user):
            return redirect(next_url)
        return super().get(request, args, kwargs)

    def get_context_data(self, **kwargs):
        """Add the intent, corresponding service, and next_url to the context."""
        context = super().get_context_data()
        context["intent"] = self.request.GET.get("intent")
        context["service"] = Service.objects.filter(slug=context["intent"]).first()
        context["next_url"] = self.get_next_url()
        return context


def mailgun_webhook(request):
    """Handle mailgun webhooks to keep track of user emails that have failed"""
    # pylint: disable=too-many-return-statements

    def verify(event):
        """Verify that the message is from mailgun"""
        token = event.get("token", "")
        timestamp = event.get("timestamp", "")
        signature = event.get("signature", "")
        hmac_digest = hmac.new(
            key=settings.MAILGUN_ACCESS_KEY.encode("utf8"),
            msg=f"{timestamp}{token}".encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        match = hmac.compare_digest(signature, str(hmac_digest))
        return match and int(timestamp) + 300 > time.time()

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("JSON decode error")

    if not verify(event.get("signature", {})):
        return HttpResponseForbidden()

    if "event-data" not in event:
        return HttpResponseBadRequest("Missing event-data")
    event = event["event-data"]

    if event.get("event") != "failed":
        return HttpResponse("OK")

    if "recipient" not in event:
        return HttpResponseBadRequest("Missing recipient")
    email = event["recipient"]

    User.objects.filter(email=email).update(email_failed=True)
    ReceiptEmail.objects.filter(email=email).update(failed=True)
    return HttpResponse("OK")


class Receipts(LoginRequiredMixin, TemplateView):
    """Subclass to view individual's receipts"""

    template_name = "organizations/organization_receipts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["organizations"] = self.request.user.organizations.filter(
            memberships__admin=True
        ).prefetch_related("charges")
        return context
