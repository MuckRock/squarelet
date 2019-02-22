# Django
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import CICharField, CIEmailField
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.db import models, transaction
from django.http.request import urlencode
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Standard Library
import uuid

# Third Party
import sesame
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.mixins import AvatarMixin
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.models import Organization

# Local
from .managers import UserManager
from .validators import UsernameValidator


class User(AvatarMixin, AbstractBaseUser, PermissionsMixin):
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

    # XXX finish doc string

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # XXX should this be optional or not?  what do we sign off as on requests?
    # do we want a full name and a short name?
    # remove blank
    name = models.CharField(_("name of user"), blank=True, max_length=255)
    email = CIEmailField(_("email"), unique=True, null=True)
    username = CICharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and ./-/_ only.  "
            "May only be changed once."
        ),
        validators=[UsernameValidator()],
        error_messages={"unqiue": _("A user with that username already exists.")},
    )
    avatar = ImageField(_("avatar"), upload_to="avatars", blank=True)
    can_change_username = models.BooleanField(
        _("can change username"),
        default=True,
        help_text=_(
            "Keeps track of whether or not the user has used their one "
            "username change"
        ),
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
    is_agency = models.BooleanField(
        _("agency user"),
        default=False,
        help_text=_(
            "This is an account used for allowing agencies to log in to the site"
        ),
    )
    source = models.CharField(
        max_length=11,
        choices=(
            ("muckrock", _("MuckRock")),
            ("documentcloud", _("DocumentCloud")),
            ("foiamachine", _("FOIA Machine")),
            ("quackbot", _("QuackBot")),
            ("squarelet", _("Squarelet")),
        ),
        default="squarelet",
    )
    email_failed = models.BooleanField(
        _("email failed"),
        default=False,
        help_text=_("Has an email we sent to this user's email address failed?"),
    )

    created_at = AutoCreatedField(_("created at"))
    updated_at = AutoLastModifiedField(_("updated at"))

    # preferences
    use_autologin = models.BooleanField(
        _("use autologin"),
        default=True,
        help_text=(
            "Links you receive in emails from us will contain"
            " a token to automatically log you in"
        ),
    )

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    default_avatar = static("images/avatars/profile.png")

    objects = UserManager()

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: send_cache_invalidations("user", self.pk))

    def get_absolute_url(self):
        return reverse("users:detail", kwargs={"username": self.username})

    def get_full_name(self):
        return self.name

    def safe_name(self):
        if self.name:
            return self.name
        return self.username

    @mproperty
    def individual_organization(self):
        """A user's individual organization has a matching UUID"""
        return Organization.objects.get(id=self.id)

    def wrap_url(self, url, **extra):
        """Wrap a URL for autologin"""
        if not self.use_autologin:
            return url

        extra.update(sesame.utils.get_parameters(self))
        return "{}?{}".format(url, urlencode(extra))
