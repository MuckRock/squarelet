# Django
from django.contrib import messages

# Third Party
from allauth.account import signals
from allauth.account.forms import AddEmailForm
from allauth.account.models import EmailAddress, EmailConfirmation, EmailConfirmationHMAC
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

# Squarelet
from squarelet.email_api.serializers import PressPassEmailAddressSerializer


class PressPassEmailConfirmationViewSet(
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = EmailConfirmation.objects.none()
    lookup_field = "key"

    def update(self, request, key=None, partial=False):
        try:
            confirmation = EmailConfirmationHMAC.from_key(key)
            confirmation.confirm(self.request)
            serializer = PressPassEmailAddressSerializer(confirmation.email_address)
            return Response(serializer.data)

        except EmailConfirmation.DoesNotExist:
            return Response(
                "Please specify a valid key", status=status.HTTP_400_BAD_REQUEST
            )


class PressPassEmailAddressViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = EmailAddress.objects.none()
    lookup_field = "email"
    lookup_value_regex = "[^/]+"
    serializer_class = PressPassEmailAddressSerializer

    # def get_serializer_context(self):
    #     """
    #     pass request attribute to serializer
    #     """
    #     context = super(PressPassEmailAddressViewSet, self).get_serializer_context()

    def list(self, request, user_uuid=None):
        queryset = EmailAddress.objects.filter(user=request.user)
        serializer = PressPassEmailAddressSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, user_uuid=None):
        # use allauth's form to create the email address
        form = AddEmailForm(data=request.data, user=request.user)

        if form.is_valid():
            email_address = form.save(self.request)

            # just so we can return this to the client
            serializer = PressPassEmailAddressSerializer(email_address)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                "Please specify a valid email confirmation key", status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, user_uuid=None, email=None, partial=False):
        try:
            email_address = EmailAddress.objects.get_for_user(
                user=request.user, email=email
            )
            serializer = self.get_serializer(instance=email_address, data=request.data)
            if serializer.is_valid():
                try:
                    from_email_address = EmailAddress.objects.get(
                        user=request.user, primary=True
                    )
                except EmailAddress.DoesNotExist:
                    from_email_address = None
                email_address.set_as_primary()

                if from_email_address is not None:
                    signals.email_changed.send(
                        sender=request.user.__class__,
                        request=request,
                        user=request.user,
                        from_email_address=from_email_address,
                        to_email_address=email_address,
                    )
                return Response(email)
            else:
                return Response("You can only make a verified email address primary.", status=status.HTTP_400_BAD_REQUEST)

        except EmailAddress.DoesNotExist:
            return Response(
                "Please enter a valid email address", status=status.HTTP_400_BAD_REQUEST
            )

    def destroy(self, request, user_uuid=None, email=None):
        try:
            email_address = EmailAddress.objects.get(user=request.user, email=email)
            if email_address.primary:
                return Response(
                    "You cannot remove your primary email address.",
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                email_address.delete()
                signals.email_removed.send(
                    sender=request.user.__class__,
                    request=request,
                    user=request.user,
                    email_address=email_address,
                )
                return Response("", status=status.HTTP_204_NO_CONTENT)
        except EmailAddress.DoesNotExist:
            return Response(
                "Please enter a valid email address", status=status.HTTP_400_BAD_REQUEST
            )
