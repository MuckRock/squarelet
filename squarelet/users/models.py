# Django
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models, transaction
from django.db.models import Q
from django.http.request import urlencode
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# Third Party
import sesame
from memoize import mproperty
from sorl.thumbnail import ImageField

# Squarelet
from squarelet.core.fields import AutoCreatedField, AutoLastModifiedField
from squarelet.core.mixins import AvatarMixin
from squarelet.core.utils import file_path
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.models import Organization

# Local
from .managers import UserManager
from .validators import UsernameValidator


def user_file_path(instance, filename):
    return file_path("avatars", instance, filename)


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
    email = models.EmailField(
        _("email"),
        unique=True,
        null=True,
        help_text=_("The user's email address"),
        db_collation="case_insensitive",
    )
    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and ./-/_ only.  "
            "May only be changed once."
        ),
        validators=[UsernameValidator()],
        error_messages={"unqiue": _("A user with that username already exists.")},
        db_collation="case_insensitive",
    )
    avatar = ImageField(
        _("avatar"),
        upload_to=user_file_path,
        blank=True,
        max_length=255,
        help_text=_("An image to represent the user"),
    )
    bio = models.TextField(
        _("bio"), blank=True, help_text=_("Public bio for the user, in Markdown")
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
        max_length=13,
        choices=(
            ("muckrock", _("MuckRock")),
            ("documentcloud", _("DocumentCloud")),
            ("foiamachine", _("FOIA Machine")),
            ("squarelet", _("Squarelet")),
            ("election-hub", _("Election Hub")),
            ("biglocalnews", _("Big Local News")),
            ("agendawatch", _("Agenda Watch")),
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

    class Meta:
        ordering = ("username",)

    def __str__(self):
        return self.username

    @property
    def uuid(self):
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

        return f"{url}?{urlencode(extra)}"

    def verified_journalist(self):
        return self.organizations.filter(verified_journalist=True).exists()

    def is_hub_eligible(self):
        return self.organizations.filter(
            Q(hub_eligible=True)
            | Q(groups__hub_eligible=True)
            | Q(parent__hub_eligible=True)
        ).exists()

    def get_potential_organizations(self):
        # Get all verified email addresses for the user
        emails = self.emailaddress_set.filter(verified=True)

        # Extract the domains from the verified emails
        domains = [email.email.split('@')[1].lower() for email in emails]

        # Find organizations matching any of the domains
        return Organization.objects.filter(domains__domain__in=domains).distinct()


class LoginLog(models.Model):
    """Log when a user users Squarelet to log in to another service"""

    user = models.ForeignKey(
        verbose_name=_("user"),
        to="users.User",
        on_delete=models.PROTECT,
        related_name="logins",
    )
    client = models.ForeignKey(
        verbose_name=_("client"),
        to="oidc_provider.Client",
        on_delete=models.PROTECT,
        related_name="logins",
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
    )
    created_at = AutoCreatedField(_("created at"))

    class Meta:
        ordering = ("created_at",)
