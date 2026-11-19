# Django
from django.template import Context, Template
from django.template.loader import render_to_string

# Third Party
import pytest

# Squarelet
from squarelet.core.usage import get_usage_stats
from squarelet.organizations.tests.factories import OrganizationFactory
from squarelet.services.tests.factories import ServiceFactory
from squarelet.users.tests.factories import UserFactory


def _requests(per_month=0, monthly=0, number=0):
    return {
        "requests_per_month": per_month,
        "monthly_requests": monthly,
        "number_requests": number,
    }


@pytest.fixture(name="services")
def fixture_services():
    return {
        "muckrock": ServiceFactory(slug="muckrock"),
        "documentcloud": ServiceFactory(slug="documentcloud"),
    }


@pytest.mark.django_db
class TestGetUsageStats:
    def test_nothing_is_shown_without_stats(self):
        user = UserFactory(client_stats={})
        org = OrganizationFactory(client_stats={})

        assert not get_usage_stats(user, [org])

    def test_a_service_with_no_stats_is_left_out(self, services):
        org = OrganizationFactory(
            client_stats={"muckrock": {"requests": _requests(per_month=10)}}
        )

        assert list(get_usage_stats(org, [])) == [services["muckrock"].name]

    def test_an_organization_reads_its_own_balances(self, services):
        org = OrganizationFactory(
            client_stats={
                "muckrock": {"requests": _requests(per_month=50, monthly=20, number=7)}
            }
        )

        assert get_usage_stats(org, [])[services["muckrock"].name]["request"] == {
            "allowance_monthly": 50,
            "used_monthly": 30,
            "available_purchased": 7,
            "available_inherited": 0,
        }

    def test_a_user_reads_their_individual_balances_not_their_orgs(self, services):
        user = UserFactory(
            client_stats={
                "muckrock": {
                    "individual_requests": _requests(per_month=5, monthly=1, number=2),
                    "requests": _requests(per_month=100, monthly=100, number=100),
                }
            }
        )

        stats = get_usage_stats(user, [])[services["muckrock"].name]["request"]

        assert stats["allowance_monthly"] == 5
        assert stats["used_monthly"] == 4
        assert stats["available_purchased"] == 2

    def test_inherited_balances_add_up_across_orgs(self, services):
        user = UserFactory(client_stats={})
        org_a = OrganizationFactory(
            client_stats={"muckrock": {"requests": _requests(monthly=10, number=3)}}
        )
        org_b = OrganizationFactory(
            client_stats={"muckrock": {"requests": _requests(monthly=5, number=1)}}
        )
        org_without_stats = OrganizationFactory(client_stats={})

        stats = get_usage_stats(user, [org_a, org_b, org_without_stats])

        assert stats[services["muckrock"].name]["request"] == {
            "allowance_monthly": 0,
            "used_monthly": 0,
            "available_purchased": 0,
            "available_inherited": 19,
        }

    def test_null_balances_count_as_zero(self, services):
        org = OrganizationFactory(
            client_stats={
                "documentcloud": {
                    "ai_credits": {
                        "ai_credits_per_month": None,
                        "monthly_ai_credits": None,
                        "number_ai_credits": 4,
                    }
                }
            }
        )

        assert get_usage_stats(org, [])[services["documentcloud"].name][
            "AI credit"
        ] == {
            "allowance_monthly": 0,
            "used_monthly": 0,
            "available_purchased": 4,
            "available_inherited": 0,
        }


@pytest.mark.django_db
def test_a_service_without_a_row_is_labelled_by_its_slug(monkeypatch):
    # Migrations seed a `muckrock` row, so only an unknown slug has none.
    monkeypatch.setattr(
        "squarelet.core.usage.USAGE_RESOURCES", {"unlisted": [("requests", "request")]}
    )
    org = OrganizationFactory(
        client_stats={"unlisted": {"requests": _requests(per_month=10)}}
    )

    assert list(get_usage_stats(org, [])) == ["unlisted"]


def _progress_bar(value, max_value):
    return Template(
        '{% include "widgets/progress_bar.html" with value=value max=max %}'
    ).render(Context({"value": value, "max": max_value}))


class TestProgressBar:
    def test_below_ninety_percent_is_unmarked(self):
        html = _progress_bar(89, 100)

        assert 'class="progress-bar "' in html
        assert "width: 89%" in html

    def test_ninety_percent_is_a_caution(self):
        assert "progress-bar caution" in _progress_bar(90, 100)

    def test_the_full_allowance_is_a_danger(self):
        assert "progress-bar danger" in _progress_bar(100, 100)

    def test_over_the_allowance_is_a_danger(self):
        assert "progress-bar danger" in _progress_bar(120, 100)


def _card(stats, individual=False):
    return " ".join(
        render_to_string(
            "organizations/includes/usage_card.html",
            {
                "usage_stats": {"MuckRock": {"request": stats}},
                "individual": individual,
            },
        ).split()
    )


def _card_stats(allowance=0, used=0, purchased=0, inherited=0):
    return {
        "allowance_monthly": allowance,
        "used_monthly": used,
        "available_purchased": purchased,
        "available_inherited": inherited,
    }


class TestUsageCard:
    def test_a_monthly_allowance_shows_how_much_is_used(self):
        html = _card(_card_stats(allowance=1000, used=250))

        assert "Monthly requests" in html
        assert "250 / 1,000 used" in html
        assert 'role="progressbar"' in html
        assert "used all of" not in html

    def test_no_allowance_shows_no_progress_bar(self):
        html = _card(_card_stats(purchased=3))

        assert "Monthly requests" not in html
        assert "Requests" in html
        assert 'role="progressbar"' not in html

    def test_an_exhausted_allowance_is_called_out(self):
        html = _card(_card_stats(allowance=10, used=10))

        assert "This organization has used all of its monthly requests." in html

    def test_a_user_is_addressed_directly(self):
        html = _card(_card_stats(allowance=10, used=10, purchased=2), individual=True)

        assert "You have used all of your monthly requests." in html
        assert "You have <strong>2 requests</strong> that never expire." in html

    def test_a_single_purchased_request_is_singular(self):
        html = _card(_card_stats(purchased=1))

        assert (
            "This organization has <strong>1 request</strong> that never expires."
            in html
        )

    def test_inherited_requests_are_attributed_to_memberships(self):
        html = _card(_card_stats(inherited=100), individual=True)

        assert (
            "You have <strong>100 additional requests</strong> "
            "from your organization memberships." in html
        )

    def test_more_than_100_inherited_requests_shows_100_plus(self):
        html = _card(_card_stats(inherited=1500))

        assert (
            "This organization has <strong>100+ additional requests</strong> "
            "from its organization memberships." in html
        )
        assert "1,500" not in html

    def test_a_single_inherited_request_is_singular(self):
        html = _card(_card_stats(inherited=1))

        assert "<strong>1 additional request</strong>" in html

    def test_empty_balances_say_nothing(self):
        html = _card(_card_stats())

        assert "never expire" not in html
        assert "additional" not in html
        assert "used all of" not in html
