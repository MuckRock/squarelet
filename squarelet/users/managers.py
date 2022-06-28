# Django
from django.contrib.auth.models import UserManager as AuthUserManager
from django.db import transaction

# Third Party
import stripe

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import Organization


class UserManager(AuthUserManager):
    def _create_user(self, username, email, password=None, uuid=None, **extra_fields):
        """Create and save a user with the given username, email, and password."""
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

        plan = user_data.get("plan")
        try:
            if plan and plan.for_individuals:
                # Ensure organization is in the database before start subscription
                # on stripe, so that the stripe call back will definitely be able
                # to load the organization
                transaction.on_commit(
                    lambda: user.individual_organization.create_subscription(
                        user_data.get("stripe_token"), plan
                    )
                )

            if plan and plan.for_groups:
                group_organization = Organization.objects.create(
                    name=user_data["organization_name"]
                )
                group_organization.add_creator(user)
                group_organization.change_logs.create(
                    reason=ChangeLogReason.created,
                    user=user,
                    to_plan=plan,
                    to_max_users=group_organization.max_users,
                )
                transaction.on_commit(
                    lambda: group_organization.create_subscription(
                        user_data.get("stripe_token"), plan
                    )
                )
            else:
                group_organization = None
        except stripe.error.StripeError as exc:
            error = "Payment error: {}".format(exc.user_message)
        else:
            error = None

        return user, group_organization, error
