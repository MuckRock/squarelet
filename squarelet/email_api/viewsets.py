# Django
from django.shortcuts import get_object_or_404

# Third Party
from allauth.account import signals
from allauth.account.forms import AddEmailForm
from allauth.account.models import (
    EmailAddress,
    EmailConfirmation,
    EmailConfirmationHMAC,
)
from rest_framework import mixins, status, views, viewsets
from rest_framework.response import Response

# Squarelet
from squarelet.email_api.serializers import PressPassEmailAddressSerializer


class PressPassEmailConfirmationUpdateView(views.APIView):
    queryset = EmailConfirmation.objects.none()
    lookup_field = "key"

    def patch(self, request, key=None):
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

    def get_queryset(self):
        return EmailAddress.objects.filter(user=self.request.user)

    def create(self, request):
        # use allauth's form to create the email address
        form = AddEmailForm(data=request.data, user=request.user)

        if form.is_valid():
            email_address = form.save(self.request)

            # just so we can return this to the client
            serializer = PressPassEmailAddressSerializer(email_address)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                "Please specify a valid email confirmation key",
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_update(self, serializer):
        if serializer.is_valid():
            old_primary = EmailAddress.objects.get_primary(self.request.user)
            serializer.instance.set_as_primary()

            signals.email_changed.send(
                sender=self.request.user.__class__,
                request=self.request,
                user=self.request.user,
                from_email_address=old_primary,
                to_email_address=serializer.instance,
            )

            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, email=None):
        email_address = self.get_object()

        if email_address.primary:
            return Response(
                "You cannot delete your primary email address",
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
