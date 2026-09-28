# Third Party
import pytest

# Squarelet
from squarelet.organizations.plan_mapping import LEGACY_PLAN_MAP, resolve_target


class TestPrivatePlansHaveATarget:
    """Plans granted to particular organizations land on a canonical price."""

    @pytest.mark.parametrize(
        "slug, target",
        [
            ("organization-annual", ("organization", "annual", "standard", "")),
            (
                "sunlight-enterprise-annual",
                ("sunlight-enterprise", "annual", "standard", ""),
            ),
            ("custom-crp", ("organization", "monthly", "standard", "")),
            (
                "documentcloud-premium",
                ("documentcloud-premium", "monthly", "standard", ""),
            ),
        ],
    )
    def test_at_list_price(self, slug, target):
        assert resolve_target(slug) == target

    @pytest.mark.parametrize(
        "slug, code",
        [
            ("election-accountability-cohort", "election-cohort"),
            ("sunlight-basic-annual", "legacy-basic"),
        ],
    )
    def test_at_a_negotiated_rate(self, slug, code):
        """Reaching one takes being granted its plan."""
        assert resolve_target(slug)[::3] == ("sunlight-essential", code)

    def test_flexible_users_migrates_comped_and_is_never_sold(self):
        slug = "organization-flexible-users-annual"

        assert LEGACY_PLAN_MAP[(slug, False)] == (
            "organization",
            "monthly",
            "comped",
            "",
        )
        assert resolve_target(slug) is None
