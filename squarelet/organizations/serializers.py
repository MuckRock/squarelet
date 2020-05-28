# Django
from django.db.models.expressions import F

# Third Party
import stripe
from oidc_provider.models import Client
from rest_flex_fields import FlexFieldsModelSerializer
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

# Squarelet
from squarelet.organizations.choices import StripeAccounts
from squarelet.organizations.models import (
    Charge,
    Entitlement,
    Invitation,
    Membership,
    Organization,
    Plan,
    Subscription,
)


class OrganizationSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    # remove plan once all clients are updated to handle entitlements
    plan = serializers.SerializerMethodField()
    entitlements = serializers.SerializerMethodField()
    card = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "plan",
            "entitlements",
            "card",
            "max_users",
            "individual",
            "private",
            "verified_journalist",
            "updated_at",
            "payment_failed",
            "avatar_url",
        )

    def get_plan(self, obj):
        return obj.plan.slug if obj.plan else "free"

    def get_entitlements(self, obj):
        request = self.context.get("request")
        if request and hasattr(request, "auth") and request.auth:
            return (
                request.auth.client.entitlements.filter(plans__organizations=obj)
                .annotate(update_on=F("plans__subscriptions__update_on"))
                .values("name", "slug", "description", "resources", "update_on")
            )
        return []

    def get_card(self, obj):
        # this can be slow - goes to stripe for customer/card info - cache this
        return obj.customer(StripeAccounts.muckrock).card_display


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer()

    class Meta:
        model = Membership
        fields = ("organization", "admin")

    def to_representation(self, instance):
        """Move fields from organization to membership representation."""
        # https://stackoverflow.com/questions/21381700/django-rest-framework-how-do-you-flatten-nested-data
        representation = super().to_representation(instance)
        organization_representation = representation.pop("organization")
        for key in organization_representation:
            representation[key] = organization_representation[key]

        return representation


class StripeError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Stripe error"


class ChargeSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True, required=False)
    save_card = serializers.BooleanField(write_only=True, required=False)
    organization = serializers.SlugRelatedField(
        slug_field="uuid", queryset=Organization.objects.all()
    )

    class Meta:
        model = Charge
        fields = (
            "amount",
            "charge_id",
            "created_at",
            "description",
            "fee_amount",
            "organization",
            "save_card",
            "token",
        )
        read_only_fields = ("created_at", "charge_id")

    def create(self, validated_data):
        """Create the charge object locally and on stripe"""
        organization = validated_data["organization"]
        try:
            charge = organization.charge(
                validated_data["amount"],
                validated_data["description"],
                validated_data.get("fee_amount", 0),
                validated_data.get("token"),
                validated_data.get("save_card"),
            )
        except stripe.error.StripeError as exc:
            raise StripeError(exc.user_message)
        # add the card display to the response, so the client has immediate access
        # to the newly saved card
        data = {"card": organization.customer(StripeAccounts.muckrock).card_display}
        data.update(self.data)
        self._data = data
        return charge

    def validate(self, attrs):
        """Must supply token if saving card"""
        if attrs.get("save_card") and not attrs.get("token"):
            raise serializers.ValidationError(
                "Must supply a token if save card is true"
            )
        return attrs


# PressPass


class PressPassOrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "uuid",
            "name",
            "slug",
            "max_users",
            "individual",
            "private",
            "updated_at",
            "payment_failed",
            "avatar",
        )
        extra_kwargs = {
            "uuid": {"read_only": True},
            "slug": {"read_only": True},
            "max_users": {"required": False},
            "individual": {"read_only": True},
            "private": {"required": False},
            "updated_at": {"read_only": True},
            "payment_failed": {"read_only": True},
            "avatar": {"required": False},
        }


class PressPassMembershipSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(slug_field="uuid", read_only=True)

    class Meta:
        model = Membership
        fields = ("user", "admin")
        extra_kwargs = {"admin": {"default": False}}


class PressPassUserMembershipsSerializer(serializers.ModelSerializer):
    organization = PressPassOrganizationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ("organization", "admin")
        extra_kwargs = {"admin": {"default": False}}


class PressPassNestedInvitationSerializer(FlexFieldsModelSerializer):
    user = serializers.SlugRelatedField(slug_field="uuid", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "uuid",
            "email",
            "user",
            "request",
            "created_at",
            "accepted_at",
            "rejected_at",
        )
        extra_kwargs = {
            "email": {"required": False},
            "request": {"read_only": True},
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
            "rejected_at": {"read_only": True},
        }
        expandable_fields = {
            "user": "squarelet.users.PressPassUserSerializer",
            "organization": PressPassOrganizationSerializer,
        }

    def validate_email(self, value):
        request = self.context.get("request")
        view = self.context.get("view")
        organization = Organization.objects.get(uuid=view.kwargs["organization_uuid"])
        if organization.has_admin(request.user) and not value:
            raise serializers.ValidationError("You must supply en email")
        elif not organization.has_admin(request.user) and value:
            raise serializers.ValidationError("You must not supply en email")
        return value


class PressPassInvitationSerializer(FlexFieldsModelSerializer):
    organization = serializers.SlugRelatedField(slug_field="uuid", read_only=True)
    user = serializers.SlugRelatedField(slug_field="uuid", read_only=True)
    accept = serializers.BooleanField(write_only=True)
    reject = serializers.BooleanField(write_only=True)

    class Meta:
        model = Invitation
        fields = (
            "organization",
            "email",
            "user",
            "request",
            "created_at",
            "accepted_at",
            "rejected_at",
            "accept",
            "reject",
        )
        extra_kwargs = {
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
            "rejected_at": {"read_only": True},
            "email": {"read_only": True},
        }
        expandable_fields = {
            "user": "squarelet.users.PressPassUserSerializer",
            "organization": PressPassOrganizationSerializer,
        }

    def validate(self, attrs):
        """Must not try to accept and reject"""
        if attrs.get("accept") and attrs.get("reject"):
            raise serializers.ValidationError(
                "May not accept and reject the invitation"
            )
        return attrs


class PressPassUserInvitationsSerializer(FlexFieldsModelSerializer):
    organization = serializers.SlugRelatedField(slug_field="uuid", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "uuid",
            "organization",
            "request",
            "accepted_at",
            "rejected_at",
            "created_at",
        )
        expandable_fields = {
            "organization": PressPassOrganizationSerializer,
            "user": "squarelet.users.PressPassUserSerializer",
        }


class PressPassPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "id",
            "name",
            "slug",
            "minimum_users",
            "base_price",
            "price_per_user",
            "public",
            "annual",
            "for_individuals",
            "for_groups",
            "entitlements",
        )


class PressPassClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ("name", "client_type", "website_url")


class PressPassEntitlmentSerializer(FlexFieldsModelSerializer):
    class Meta:
        model = Entitlement
        fields = ("name", "slug", "client", "description")
        extra_kwargs = {"slug": {"read_only": True}}
        expandable_fields = {"client": PressPassClientSerializer}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        context = kwargs.get("context", {})
        request = context.get("request")

        # may only create entitlements for your own clients
        if request and request.user and request.user.is_authenticated:
            self.fields["client"].queryset = Client.objects.filter(owner=request.user)
        else:
            self.fields["client"].queryset = Client.objects.none()


class PressPassSubscriptionSerializer(FlexFieldsModelSerializer):
    token = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Subscription
        fields = ("id", "plan", "update_on", "cancelled", "token")
        extra_kwargs = {
            "update_on": {"read_only": True},
            "cancelled": {"read_only": True},
        }
        expandable_fields = {"plan": PressPassPlanSerializer}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        context = kwargs.get("context", {})
        view = context.get("view")
        organization = Organization.objects.get(uuid=view.kwargs["organization_uuid"])
        self.fields["plan"].queryset = Plan.objects.choices(organization)

    def validate(self, attrs):
        """Check the permissions"""
        request = self.context.get("request")
        view = self.context.get("view")
        organization = Organization.objects.get(uuid=view.kwargs["organization_uuid"])

        # only modify subscriptions for organizations you have admin access to
        if not request.user.has_perm("organizations.change_organization", organization):
            raise serializers.ValidationError(
                "You may only modify subscriptions for organizations you are "
                "an admin for"
            )

        # token is required if paid plan unless you have a card on file
        payment_required = attrs["plan"].requires_payment()
        card_on_file = organization.customer(attrs["plan"].stripe_account).card
        if payment_required and not card_on_file and not attrs.get("token"):
            raise serializers.ValidationError("Must supply a credit card for paid plan")

        return attrs

    def validate_plan(self, value):
        """Cannot switch between plans that are paid to different stripe accounts"""
        if self.instance and self.instance.plan.stripe_account != value.stripe_account:
            raise serializers.ValidationError(
                "You may not switch to a plan paid to a different company.  "
                "Please cancel this plan and create a new one."
            )
        return value
