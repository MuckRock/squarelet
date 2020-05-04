# Django
from django.shortcuts import get_object_or_404

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

    def get_object(self, email):
        return get_object_or_404(EmailAddress, email=email)

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
        email_address = self.get_object(email)
        serializer = self.get_serializer(instance=email_address, data=request.data)

        if serializer.is_valid() and serializer.is_valid_update(request.data):
            email_address.set_as_primary()

            try:
                from_email_address = EmailAddress.objects.get(
                    user=request.user, primary=True
                )
            except EmailAddress.DoesNotExist:
                from_email_address = None

            signals.email_changed.send(
                sender=request.user.__class__,
                request=request,
                user=request.user,
                from_email_address=from_email_address,
                to_email_address=email_address,
            )

            return Response(serializer.data)
        else:
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

    def destroy(self, request, user_uuid=None, email=None):
        email_address = self.get_object(email)
        serializer = self.get_serializer(instance=email_address)

        if serializer.is_valid_delete(email_address):
            email_address.delete()
            signals.email_removed.send(
                sender=request.user.__class__,
                request=request,
                user=request.user,
                email_address=email_address,
            )
            return Response("", status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
