# Django
from django.conf import settings
from django.db import transaction

# Third Party
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

# Squarelet
from squarelet.organizations.models import Membership, Organization


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, user, form, commit=True):
        """Save the user's full name"""
        with transaction.atomic():
            user.name = form.cleaned_data.get("name", "")
            user = super().save_user(request, user, form, commit)
            # XXX validate things here - ie ensure name uniqueness
            organization = Organization.objects.create(
                id=user.pk,
                name=user.username,
                individual=True,
                private=True,
                max_users=1,
            )
            Membership.objects.create(user=user, organization=organization, admin=True)
        return user


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)
