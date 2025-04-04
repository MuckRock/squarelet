# Django
from django.contrib.auth.models import UserManager as AuthUserManager
from django.db import transaction

# Squarelet
from squarelet.core.utils import mailchimp_journey
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import Organization


class UserManager(AuthUserManager):
    def _create_user(self, username, email, password=None, **extra_fields):
        """Create and save a user with the given username, email, and password."""
        uuid = extra_fields.pop("uuid", None)
        if not username:
            raise ValueError("The given username must be set")
        email = self.normalize_email(email)
        if not email:
            # if email is blank, set it to NULL to avoid unique constraint
            email = None
        username = self.model.normalize_username(username)
        user = self.model(username=username, email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        # all users must have an individual organization
        Organization.objects.create_individual(user, uuid)

        return user

    @transaction.atomic
    def register_user(self, user_data):
        """Registration logic"""
        user = self.create_user(
            username=user_data.get("username"),
            email=user_data.get("email"),
            password=user_data.get("password1"),
            name=user_data.get("name"),
            source=user_data.get("source"),
        )

        if user.source == "election-hub":
            mailchimp_journey(user.email, "keh")
        elif user.source == "muckrock":
            mailchimp_journey(user.email, "welcome_mr")
        elif user.source in ["squarelet", "foiamachine"]:
            mailchimp_journey(user.email, "welcome_sq")

        return user
