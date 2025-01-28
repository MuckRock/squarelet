from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from io import StringIO
import os
import json
from squarelet.users.tests.factories import UserFactory
from squarelet.organizations.tests.factories import OrganizationFactory


class TestGenerateFixtures(TestCase):
    def setUp(self):
        self.output_dir = 'test_fixtures'
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def tearDown(self):
        # Clean up test fixtures
        for file in os.listdir(self.output_dir):
            os.remove(os.path.join(self.output_dir, file))
        os.rmdir(self.output_dir)

    def test_generate_fixtures(self):
        # Execute command
        out = StringIO()
        call_command(
            'generate_fixtures',
            count=2,
            output_dir=self.output_dir,
            stdout=out
        )

        # Verify files exist
        expected_files = [
            'users_user.json',
            'organizations_organization.json'
        ]
        for filename in expected_files:
            filepath = os.path.join(self.output_dir, filename)
            self.assertTrue(
                os.path.exists(filepath),
                f"Missing fixture file: {filename}"
            )

        # Verify content structure
        with open(os.path.join(self.output_dir, 'users_user.json')) as f:
            data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['model'], 'users.user')
