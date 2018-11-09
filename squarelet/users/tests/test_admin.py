# Third Party
from test_plus.test import TestCase

# Local
from ..admin import MyUserCreationForm


class TestMyUserCreationForm(TestCase):
    def setUp(self):
        self.user = self.make_user("notalamode", "notalamodespassword")

    def test_clean_username_success(self):
        # Instantiate the form with a new username
        form = MyUserCreationForm(
            {
                "username": "alamode",
                "email": "alamode@example.com",
                "password1": "7jefB#f@Cc7YJB]2v",
                "password2": "7jefB#f@Cc7YJB]2v",
            }
        )
        # Run is_valid() to trigger the validation
        valid = form.is_valid()
        assert valid

    def test_clean_username_false(self):
        # Instantiate the form with the same username as self.user
        form = MyUserCreationForm(
            {
                "username": self.user.username,
                "email": "alamode@example.com",
                "password1": "notalamodespassword",
                "password2": "notalamodespassword",
            }
        )
        # Run is_valid() to trigger the validation, which is going to fail
        # because the username is already taken
        valid = form.is_valid()
        assert not valid

        # The form.errors dict should contain a single error called 'username'
        assert len(form.errors) == 1
        assert "username" in form.errors
