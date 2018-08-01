# Django
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import CICharField, CIEmailField
from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid

# Local
from ..core.fields import AutoCreatedField, AutoLastModifiedField
from .managers import UserManager
from .validators import UsernameValidator


class User(AbstractBaseUser, PermissionsMixin):
    """User model for squarelet

    This is a general user model which should only store information applicable
    to all of the different services which will be authenticating against
    squarelet

    Attributes:
        # AbstractBaseUser
        password (CharField): the hashed password
        last_login (DateTimeField): date time of last login

        # PermissionsMixin
        is_superuser (BooleanField): designates this user as having all permissions
        groups (ManyToManyField): groups the user are in - they will receive
            permissions from their groups
        user_permissions (ManyToManyField): permissions for this user

        # defined here
        name (CharField): full name for the user
        username (CharField): a unique name for each user
        is_staff (BooleanField):
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # should this be optional or not?  what do we sign off as on requests?
    # do we want a full name and a short name?
    name = models.CharField(_("name of user"), blank=True, max_length=255)
    email = CIEmailField(_("email"), unique=True)
    username = CICharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and ./+/-/_ only"
        ),
        validators=[UsernameValidator()],
        error_messages={"unqiue": _("A user with that username already exists.")},
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()

    def __str__(self):
        return self.username

    def get_absolute_url(self):
        return reverse("users:detail", kwargs={"username": self.username})

    def get_full_name(self):
        return self.name
