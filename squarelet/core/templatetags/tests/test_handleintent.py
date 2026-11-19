# Django
from django.template import Context, Template

# Third Party
import pytest

# Squarelet
from squarelet.core.templatetags.handleintent import services_dropdown
from squarelet.services.models import Service
from squarelet.services.tests.factories import ServiceFactory


@pytest.mark.django_db
def test_the_dropdown_groups_services_by_provider():
    Service.objects.all().delete()
    documentcloud = ServiceFactory(name="DocumentCloud", provider_name="MuckRock")
    foia = ServiceFactory(name="FOIA Machine", provider_name="MuckRock")
    agenda = ServiceFactory(name="Agenda Watch", provider_name="Big Local News")

    context = services_dropdown()

    assert list(context["muckrock_services"]) == [documentcloud, foia]
    assert list(context["partner_services"]) == [agenda]


@pytest.mark.django_db
def test_the_dropdown_leaves_out_services_without_a_link():
    Service.objects.all().delete()
    ServiceFactory(provider_name="MuckRock", base_url=None)
    ServiceFactory(provider_name="Big Local News", base_url="")

    context = services_dropdown()

    assert not context["muckrock_services"]
    assert not context["partner_services"]


@pytest.mark.django_db
def test_only_partner_services_carry_a_provider_byline():
    Service.objects.all().delete()
    ServiceFactory(name="DocumentCloud", provider_name="MuckRock")
    ServiceFactory(name="Agenda Watch", provider_name="Big Local News")

    html = Template("{% load handleintent %}{% services_dropdown %}").render(Context())

    assert "by Big Local News" in html
    assert "by MuckRock" not in html
