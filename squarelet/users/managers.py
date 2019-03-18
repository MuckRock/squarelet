# Django
from django.contrib.auth.models import UserManager as AuthUserManager

# Squarelet
from squarelet.organizations.models import Organization


class UserManager(AuthUserManager):
    def _create_user(self, username, email, password=None, **extra_fields):
        """Create and save a user with the given username, email, and password."""
        if not username:
            raise ValueError("The given username must be set")
        email = self.normalize_email(email)
        username = self.model.normalize_username(username)
        user = self.model(username=username, email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        # all users must have an individual organization
        Organization.objects.create_individual(user)

        return user
