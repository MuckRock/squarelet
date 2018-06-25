
# Django
from django.contrib.auth.models import UserManager as AuthUserManager

# Third Party
from allauth.account.models import EmailAddress


class UserManager(AuthUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        """Create and save a user with the given username, email, and password."""
        if not username:
            raise ValueError("The given username must be set")
        email = self.normalize_email(email)
        username = self.model.normalize_username(username)
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        EmailAddress.objects.create(user=user, email=email, primary=True)
        return user
