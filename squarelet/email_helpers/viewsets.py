# Standard Library

# Third Party
from allauth.account.forms import AddEmailForm
from allauth.account.models import EmailAddress
from allauth.account.views import EmailView
from rest_framework import status, viewsets
from rest_framework.response import Response

# Squarelet
from squarelet.email_helpers.serializers import (
    PressPassEmailAddressSerializer
)


class PressPassEmailAddressViewSet(viewsets.ViewSet):
    queryset = EmailAddress.objects.none()

    def list(self, request, user_uuid=None):
        queryset = EmailAddress.objects.filter(user=self.request.user)
        serializer = PressPassEmailAddressSerializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, user_uuid=None):
        form = AddEmailForm(data=request.data, user=request.user)

        if form.is_valid():
            email_address = form.save(self.request)

            return Response(email_address.email, status=status.HTTP_201_CREATED)
        else:
            return Response(
                "Please enter a valid email address",
                status=status.HTTP_400_BAD_REQUEST
            )

    def partial_update(self, request, user_uuid=None, pk=None):
        EmailView._action_primary(EmailView, request)

        return Response(request.data, status=status.HTTP_202_ACCEPTED)

    def delete(self, request, user_uuid=None, pk=None):
        pass
