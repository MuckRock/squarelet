# Django
from django.contrib.auth.models import UserManager as AuthUserManager

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models import Organization, OrganizationChangeLog, Plan


class UserManager(AuthUserManager):
    def _create_user(self, username, email, password=None, **extra_fields):
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
        Organization.objects.create_individual(user)

        return user

    def register_user(self, user_data):
        """Registration logic"""
        user = self.create_user(
            username=user_data.get("username"),
            email=user_data.get("email"),
            password=user_data.get("password1"),
            name=user_data.get("name"),
            source=user_data.get("source"),
        )

        free_plan = Plan.objects.get(slug="free")
        plan = user_data["plan"]
        try:
            if not plan.free() and plan.for_individuals:
                user.individual_organization.set_subscription(
                    user_data.get("stripe_token"), plan, max_users=1, user=user
                )

            if not plan.free() and plan.for_groups:
                group_organization = Organization.objects.create(
                    name=user_data["organization_name"],
                    plan=free_plan,
                    next_plan=free_plan,
                )
                group_organization.add_creator(user)
                group_organization.change_logs.create(
                    reason=OrganizationChangeLog.CREATED,
                    user=user,
                    to_plan=group_organization.plan,
                    to_next_plan=group_organization.next_plan,
                    to_max_users=group_organization.max_users,
                )
                group_organization.set_subscription(
                    user_data.get("stripe_token"), plan, max_users=5, user=user
                )
            else:
                group_organization = None
        except stripe.error.StripeError as exc:
            error = "Payment error: {}".format(exc.user_message)
        else:
            error = None

        return user, group_organization, error
