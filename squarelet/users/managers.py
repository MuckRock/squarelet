# Django
from django.contrib.auth.models import UserManager as AuthUserManager
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

# Standard Library
import logging
import sys

# Squarelet
from squarelet.core.utils import mailchimp_journey
from squarelet.organizations.models import Organization

logger = logging.getLogger(__name__)


class UserManager(AuthUserManager):
    def get_searchable(self, user):
        """Return users visible in search to `user`."""
        if user.is_staff:
            return self.all()
        # Never show hidden users
        qs = self.filter(individual_organization__hidden=False)
        # Private users are only visible to org-mates
        qs = qs.filter(
            Q(individual_organization__private=False) | Q(organizations__users=user)
        ).distinct()
        return qs

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
        # Wrap in a savepoint so that a failed insert (e.g. a username
        # collision, including races that slip past form/serializer
        # validation) rolls back cleanly. Without the savepoint the
        # IntegrityError poisons the surrounding ATOMIC_REQUESTS transaction
        # and orphans the just-created organization.
        try:
            with transaction.atomic():
                Organization.objects.create_individual(user, uuid)
        except IntegrityError as exc:
            logger.warning(
                "Could not create individual organization for username %r: %s",
                username,
                exc,
                exc_info=sys.exc_info(),
            )
            raise ValidationError(
                {"username": _("A user with that username already exists.")},
                code="duplicate_username",
            ) from exc

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
