# Django
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import CICharField, CIEmailField
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.db import models, transaction
from django.http.request import urlencode
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

# Third Party
import sesame
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.mixins import AvatarMixin
from squarelet.oidc.middleware import send_cache_invalidations

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
    """

    individual_organization = models.OneToOneField(
        verbose_name=_("individual organization"),
        to="organizations.Organization",
        on_delete=models.PROTECT,
        editable=False,
        to_field="uuid",
        help_text=_(
            "This is both the UUID for the user, as well as a foreign key to the "
            "corresponding individual organization, which has the same UUID. "
            "This is used to uniquely identify the user across services."
        ),
    )
    name = models.CharField(
        _("name of user"), max_length=255, help_text=_("The user's full name")
    )
    email = CIEmailField(
        _("email"), unique=True, null=True, help_text=_("The user's email address")
    )
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
    avatar = ImageField(
        _("avatar"),
        upload_to="avatars",
        blank=True,
        max_length=255,
        help_text=_("An image to represent the user"),
    )
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
        _("source"),
        max_length=11,
        choices=(
            ("muckrock", _("MuckRock")),
            ("documentcloud", _("DocumentCloud")),
            ("foiamachine", _("FOIA Machine")),
            ("quackbot", _("QuackBot")),
            ("squarelet", _("Squarelet")),
        ),
        default="squarelet",
        help_text=_("Which service did this user originally sign up for?"),
    )
    email_failed = models.BooleanField(
        _("email failed"),
        default=False,
        help_text=_("Has an email we sent to this user's email address failed?"),
    )

    created_at = AutoCreatedField(
        _("created at"), help_text=_("When this user was created")
    )
    updated_at = AutoLastModifiedField(
        _("updated at"), help_text=_("When this user was last updated")
    )

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

    @property
    def uuid(self):
        """The UUID is the value of the foreign key to the individual organization"""
        return self.individual_organization_id

    @property
    def date_joined(self):
        """Alias date joined to create_at for third party apps"""
        return self.created_at

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: send_cache_invalidations("user", self.uuid))

    def get_absolute_url(self):
        return reverse("users:detail", kwargs={"username": self.username})

    def get_full_name(self):
        return self.name

    def safe_name(self):
        if self.name:
            return self.name
        return self.username

    @mproperty
    def primary_email(self):
        """A user's primary email object"""
        return self.emailaddress_set.filter(primary=True).first()

    def wrap_url(self, url, **extra):
        """Wrap a URL for autologin"""
        if self.use_autologin:
            extra.update(sesame.utils.get_parameters(self))

        return "{}?{}".format(url, urlencode(extra))
