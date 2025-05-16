# Django
from django.http import HttpRequest
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

# Standard Library
from urllib.parse import parse_qs

# Squarelet
from squarelet.core.templatetags.pass_query import pass_query


class PassQueryTemplateTagTest(SimpleTestCase):
    """Test the pass_query template tag"""

    def setUp(self):
        """Set up RequestFactory for all tests"""
        self.factory = RequestFactory()

    def test_empty_request(self):
        """Test with empty request parameters"""
        request = self.factory.get("/")
        context = Context({"request": request})
        result = pass_query(context)

        # Should add default intent parameter
        self.assertEqual(result, "?intent=squarelet")

    def test_existing_parameters(self):
        """Test preserving existing parameters"""
        request = self.factory.get("/?plan=pro&next=/dashboard/")
        context = Context({"request": request})
        result = pass_query(context)

        # Parse query string into dict for easier comparison
        query_dict = parse_qs(result[1:])  # Remove leading '?'

        self.assertIn("plan", query_dict)
        self.assertEqual(query_dict["plan"][0], "pro")
        self.assertIn("next", query_dict)
        self.assertEqual(query_dict["next"][0], "/dashboard/")
        self.assertIn("intent", query_dict)
        self.assertEqual(query_dict["intent"][0], "squarelet")

    def test_override_parameters(self):
        """Test overriding existing parameters"""
        request = self.factory.get("/?plan=pro&intent=muckrock")
        context = Context({"request": request})
        result = pass_query(context, intent="documentcloud")

        query_dict = parse_qs(result[1:])

        self.assertEqual(query_dict["intent"][0], "documentcloud")
        self.assertEqual(query_dict["plan"][0], "pro")

    def test_add_new_parameters(self):
        """Test adding new parameters"""
        request = self.factory.get("/?plan=pro")
        context = Context({"request": request})
        result = pass_query(context, next="/account/settings/")

        query_dict = parse_qs(result[1:])

        self.assertEqual(query_dict["plan"][0], "pro")
        self.assertEqual(query_dict["next"][0], "/account/settings/")
        self.assertIn("intent", query_dict)

    def test_remove_parameters(self):
        """Test removing parameters by setting to None"""
        request = self.factory.get("/?plan=pro&next=/dashboard/")
        context = Context({"request": request})
        result = pass_query(context, plan=None)

        query_dict = parse_qs(result[1:])

        self.assertNotIn("plan", query_dict)
        self.assertIn("next", query_dict)
        self.assertIn("intent", query_dict)

    def test_default_intent(self):
        """Test that intent is added with default if missing"""
        request = self.factory.get("/?plan=pro")
        context = Context({"request": request})
        result = pass_query(context)

        query_dict = parse_qs(result[1:])

        self.assertIn("intent", query_dict)
        self.assertEqual(query_dict["intent"][0], "squarelet")

    def test_no_request(self):
        """Test behavior when request is not in context"""
        context = Context({})
        result = pass_query(context)
        self.assertEqual(result, "")

    def test_as_template_tag(self):
        """Test using the tag in a template"""
        request = self.factory.get("/?plan=pro&next=/dashboard/")
        context = Context({"request": request})

        # Render a template with the tag
        template = Template("{% load pass_query %}{% pass_query %}")
        rendered = template.render(context)

        self.assertIn("plan", rendered)
        self.assertIn("next", rendered)
        self.assertIn("intent", rendered)

    def test_unicode_parameters(self):
        """Test with unicode characters in parameters"""
        request = self.factory.get("/?search=测试&category=café")
        context = Context({"request": request})
        result = pass_query(context)

        self.assertIn("search=", result)
        self.assertIn("category=", result)
        self.assertIn("intent=", result)
        self.assertIn("%E6%B5%8B%E8%AF%95", result)  # URL-encoded "测试"
        self.assertIn("caf%C3%A9", result)  # URL-encoded "café"

    def test_special_characters(self):
        """Test with special characters that need URL encoding"""
        request = self.factory.get("/?q=test&filter=date:>2023")
        context = Context({"request": request})
        result = pass_query(context)

        self.assertIn("filter=date%3A%3E2023", result)  # URL-encoded "date:>2023"
