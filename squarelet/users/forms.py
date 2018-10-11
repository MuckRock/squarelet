# Django
from django import forms

# Third Party
from allauth.account.forms import SignupForm as AllauthSignupForm


class SignupForm(AllauthSignupForm):
    """Add a name field to the sign up form"""

    name = forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"placeholder": "Full name"})
    )
